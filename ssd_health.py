"""Read health logs for every storage device this machine can see.

Windows and Mac: internal HDD and SSD, USB disks, flash sticks, and memory
cards. A phone on a cable is named in the same report. Android in Termux
reports the storage fields the phone exposes. A stock iPhone cannot run this.

Double-click Check-SsdHealth.cmd on Windows, or check-ssd-health.command on
a Mac. The first run downloads smartctl into the tools folder when it is
missing. Pass --scan to add a read-only filesystem check.
"""

from __future__ import annotations

import ctypes
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import platform
import plistlib
import re
import shutil
import threading
import webbrowser
import subprocess
import sys
import tempfile
import urllib.request
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

REPORT_PATH = Path(__file__).with_name("ssd-health-report.txt")
HISTORY_PATH = Path(__file__).with_name("ssd-health-history.txt")
PAGE_PATH = Path(__file__).with_name("ssd-health-report.html")
PRODUCT_NAME = "Storage Health Check"
REPORT_BLOCKS: list = []
TOOLS = Path(__file__).with_name("tools")
SMARTCTL_VERSION = "7.5"
WIN_SMARTCTL_URL = (
    "https://github.com/smartmontools/smartmontools/releases/download/"
    f"RELEASE_7_5/smartmontools-{SMARTCTL_VERSION}.win32-setup.exe"
)
MAC_SMARTCTL_URL = (
    "https://github.com/smartmontools/smartmontools/releases/download/"
    f"RELEASE_7_5/smartmontools-{SMARTCTL_VERSION}.dmg"
)
NO_HEALTH_LOG = "This device does not provide a health log."
PHONE_CABLE = "This phone is attached as a folder. The cable does not carry a health log."
PHONE_NAME = re.compile(
    r"iPhone|iPad|Apple Mobile Device|MTP Device|Android",
    re.IGNORECASE,
)

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
STORAGE_DEVICE_PROPERTY = 0
STORAGE_DEVICE_PROTOCOL_SPECIFIC_PROPERTY = 50
PROPERTY_STANDARD_QUERY = 0
PROTOCOL_TYPE_NVME = 3
NVME_DATA_TYPE_LOG_PAGE = 2
NVME_LOG_PAGE_HEALTH = 0x02
BUS_NVME = 17
CREATE_NO_WINDOW = 0x08000000
RANK = {"ok": 0, "warning": 1, "critical": 2}

kernel32 = None


class ProtocolData(ctypes.Structure):
    _fields_ = [
        ("ProtocolType", wintypes.DWORD),
        ("DataType", wintypes.DWORD),
        ("ProtocolDataRequestValue", wintypes.DWORD),
        ("ProtocolDataRequestSubValue", wintypes.DWORD),
        ("ProtocolDataOffset", wintypes.DWORD),
        ("ProtocolDataLength", wintypes.DWORD),
        ("FixedProtocolReturnData", wintypes.DWORD),
        ("ProtocolDataRequestSubValue2", wintypes.DWORD),
        ("ProtocolDataRequestSubValue3", wintypes.DWORD),
        ("ProtocolDataRequestSubValue4", wintypes.DWORD),
    ]


class ShellExecuteInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", wintypes.DWORD),
        ("hMonitor", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


PROTOCOL_SIZE = ctypes.sizeof(ProtocolData)
HEALTH_LOG_SIZE = 512

WINDOWS_INVENTORY = r"""
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false
$OutputEncoding = [Console]::OutputEncoding
$ErrorActionPreference = "Continue"
$phys = @(Get-PhysicalDisk -ErrorAction SilentlyContinue)
$disks = @()
foreach ($d in @(Get-Disk -ErrorAction SilentlyContinue)) {
  $match = $phys | Where-Object { [string]$_.DeviceId -eq [string]$d.Number } | Select-Object -First 1
  $vols = @()
  foreach ($part in @(Get-Partition -DiskNumber $d.Number -ErrorAction SilentlyContinue)) {
    $v = $null
    try { $v = $part | Get-Volume -ErrorAction SilentlyContinue } catch { $v = $null }
    if (-not $v) { continue }
    if (-not $v.FileSystem -and -not $v.DriveLetter) { continue }
    $letter = ""
    if ($v.DriveLetter) { $letter = "$($v.DriveLetter):" }
    $vols += [PSCustomObject]@{
      Letter = $letter
      FileSystem = [string]$v.FileSystem
      Label = [string]$v.FileSystemLabel
      HealthStatus = [string]$v.HealthStatus
      OperationalStatus = [string]$v.OperationalStatus
      Size = [int64]$v.Size
      Free = [int64]$v.SizeRemaining
    }
  }
  $media = ""
  if ($match) { $media = [string]$match.MediaType }
  $disks += [PSCustomObject]@{
    Number = [int]$d.Number
    FriendlyName = [string]$d.FriendlyName
    HealthStatus = [string]$d.HealthStatus
    OperationalStatus = [string]$d.OperationalStatus
    BusType = [string]$d.BusType
    Size = [int64]$d.Size
    MediaType = $media
    Volumes = @($vols)
  }
}
$phones = @()
$seen = @{}
foreach ($dev in @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue)) {
  if (-not $dev.FriendlyName) { continue }
  $name = [string]$dev.FriendlyName
  $class = [string]$dev.Class
  $phoneClass = $class -in @("WPD", "USB", "USBDevice", "AndroidUsbDeviceClass")
  $nameMatch = $name -match "iPhone|iPad|Apple Mobile Device|MTP Device|Android"
  if (-not ($class -eq "WPD" -or ($phoneClass -and $nameMatch))) { continue }
  if ($class -eq "DiskDrive") { continue }
  if ($seen.ContainsKey($name)) { continue }
  $seen[$name] = $true
  $phones += [PSCustomObject]@{
    FriendlyName = $name
    Class = $class
    Status = [string]$dev.Status
  }
}
$reliability = @()
foreach ($item in $phys) {
  $counter = $null
  try { $counter = $item | Get-StorageReliabilityCounter -ErrorAction SilentlyContinue } catch { $counter = $null }
  $reliability += [PSCustomObject]@{
    FriendlyName = [string]$item.FriendlyName
    DeviceId = [string]$item.DeviceId
    HealthStatus = [string]$item.HealthStatus
    MediaType = [string]$item.MediaType
    Temperature = $(if ($counter) { $counter.Temperature } else { $null })
    TemperatureMax = $(if ($counter) { $counter.TemperatureMax } else { $null })
    Wear = $(if ($counter) { $counter.Wear } else { $null })
    ReadLatencyMax = $(if ($counter) { $counter.ReadLatencyMax } else { $null })
    WriteLatencyMax = $(if ($counter) { $counter.WriteLatencyMax } else { $null })
  }
}
[PSCustomObject]@{
  disks = @($disks)
  phones = @($phones)
  reliability = @($reliability)
} | ConvertTo-Json -Depth 6 -Compress
"""


def host_kind() -> str:
    blob = " ".join(
        [
            sys.platform,
            platform.system(),
            platform.release(),
            platform.platform(),
            platform.machine(),
        ]
    ).lower()
    if sys.platform == "ios" or "iphone" in blob or "ipad" in blob:
        return "ios"
    if sys.platform == "darwin":
        return "mac"
    if sys.platform == "win32":
        return "windows"
    if (
        os.environ.get("ANDROID_ROOT")
        or os.environ.get("ANDROID_DATA")
        or os.environ.get("TERMUX_VERSION")
        or "android" in blob
    ):
        return "android"
    return "other"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def load_kernel32():
    global kernel32
    if kernel32 is not None:
        return kernel32
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.DeviceIoControl.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.DeviceIoControl.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    return kernel32


def elevate_and_exit() -> None:
    kernel = load_kernel32()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(ShellExecuteInfo)
    info.fMask = 0x00000040
    info.lpVerb = "runas"
    info.lpFile = sys.executable
    info.lpParameters = " ".join(f'"{arg}"' for arg in sys.argv)
    info.nShow = 1
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        print(f"Administrator approval was not granted ({ctypes.WinError(ctypes.get_last_error()).strerror}).")
        raise SystemExit(1)
    if info.hProcess:
        kernel.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = wintypes.DWORD()
        kernel.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        kernel.CloseHandle(info.hProcess)
        raise SystemExit(int(code.value))
    raise SystemExit(0)


def hidden_kwargs() -> dict:
    if sys.platform == "win32":
        return {"creationflags": CREATE_NO_WINDOW}
    return {}


def run_command(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        timeout=timeout,
        **hidden_kwargs(),
    )


def decode_output(raw: bytes) -> str:
    if not raw:
        return ""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff") or b"\x00" in raw[:80]:
        return raw.decode("utf-16", errors="replace")
    return raw.decode("utf-8", errors="replace")


def as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def as_int(value) -> int:
    if value is None or value == "":
        return 0
    return int(value)


def gb(byte_count: int) -> str:
    return f"{byte_count / 1_000_000_000:.1f} GB"


def header() -> list[str]:
    return [
        PRODUCT_NAME,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        f"System: {platform.system()} {platform.release()}",
        "",
    ]


def finish(lines: list[str]) -> str:
    lines.append("")
    lines.append(f"Report saved to {REPORT_PATH}")
    return "\n".join(lines) + "\n"


def phone_block(name: str) -> list[str]:
    return [f"Phone: {name}", f"  {PHONE_CABLE}", ""]


def flags_from_warning(warning: int) -> list[str]:
    flags = []
    if warning & 0x01:
        flags.append("spare space is below the drive's own limit")
    if warning & 0x02:
        flags.append("temperature is outside the drive's own limit")
    if warning & 0x04:
        flags.append("the drive reports its reliability has degraded")
    if warning & 0x08:
        flags.append("the drive is in read-only mode")
    if warning & 0x10:
        flags.append("the drive's backup power failed")
    return flags


def u128(blob: bytes, offset: int) -> int:
    return int.from_bytes(blob[offset : offset + 16], "little")


def parse_health_log(log: bytes) -> dict:
    warning = log[0]
    temp_k = int.from_bytes(log[1:3], "little")
    temp_c = temp_k - 273 if temp_k else None
    return {
        "critical_warning": warning,
        "warning_flags": flags_from_warning(warning),
        "temperature_c": temp_c,
        "available_spare": log[3],
        "spare_threshold": log[4],
        "percent_used": log[5],
        "data_read": gb(u128(log, 32) * 512_000),
        "data_written": gb(u128(log, 48) * 512_000),
        "power_cycles": u128(log, 112),
        "power_on_hours": u128(log, 128),
        "unsafe_shutdowns": u128(log, 144),
        "media_errors": u128(log, 160),
        "error_log_entries": u128(log, 176),
        "minutes_over_warning_temp": int.from_bytes(log[192:196], "little"),
        "minutes_over_critical_temp": int.from_bytes(log[196:200], "little"),
        "spare_known": True,
        "percent_known": True,
        "media_known": True,
    }


def judge(health: dict) -> tuple[str, list[str]]:
    reasons = list(health["warning_flags"])
    level = "critical" if reasons else "ok"
    if health["media_errors"]:
        level = "critical"
        reasons.append(f"media errors: {health['media_errors']}")
    if health["available_spare"] <= health["spare_threshold"]:
        level = "critical"
        reasons.append(
            f"spare space {health['available_spare']}% is at or below "
            f"the limit of {health['spare_threshold']}%"
        )
    used = health["percent_used"]
    if used >= 90:
        level = "critical"
        reasons.append(f"life used {used}%")
    elif used >= 70 and level == "ok":
        level = "warning"
        reasons.append(f"life used {used}%")
    temp = health["temperature_c"]
    if temp is not None and temp >= 80:
        level = "critical"
        reasons.append(f"temperature is {temp} C")
    elif temp is not None and temp >= 70 and level == "ok":
        level = "warning"
        reasons.append(f"temperature is {temp} C")
    if health["minutes_over_critical_temp"] and level == "ok":
        level = "warning"
        reasons.append(
            f"it has spent {health['minutes_over_critical_temp']} minutes "
            "over its critical temperature"
        )
    if not reasons:
        reasons.append("the drive's own health log does not report a failure")
    return level, reasons


def verdict(health: dict) -> tuple[str, list[str]]:
    level, reasons = judge(health)
    reallocated = health.get("reallocated") or 0
    if reallocated:
        reasons = [item for item in reasons if "does not report a failure" not in item]
        reasons.append(f"reallocated sectors: {reallocated}")
        if level == "ok":
            level = "warning"
    return level, reasons


def blank_health(**overrides) -> dict:
    health = {
        "warning_flags": [],
        "temperature_c": None,
        "available_spare": 100,
        "spare_threshold": 0,
        "percent_used": 0,
        "media_errors": 0,
        "minutes_over_critical_temp": 0,
        "reallocated": 0,
    }
    health.update(overrides)
    return health


def health_from_smartctl(data: dict) -> dict | None:
    if not isinstance(data, dict):
        return None
    support = data.get("smart_support") or {}
    if support.get("available") is False:
        return None
    nvme = data.get("nvme_smart_health_information_log")
    if isinstance(nvme, dict) and nvme:
        warning = int(nvme.get("critical_warning") or 0)
        spare = nvme.get("available_spare")
        threshold = nvme.get("available_spare_threshold")
        if spare is None:
            spare = 100
            threshold = 0
        elif threshold is None:
            threshold = 0
        health = blank_health(
            warning_flags=flags_from_warning(warning),
            temperature_c=nvme.get("temperature"),
            available_spare=int(spare),
            spare_threshold=int(threshold),
            percent_used=int(nvme.get("percentage_used") or 0),
            media_errors=int(nvme.get("media_errors") or 0),
            minutes_over_critical_temp=int(nvme.get("critical_comp_time") or 0),
            spare_known="available_spare" in nvme,
            percent_known="percentage_used" in nvme,
            media_known=True,
        )
        if nvme.get("data_units_read") is not None:
            health["data_read"] = gb(int(nvme["data_units_read"]) * 512_000)
        if nvme.get("data_units_written") is not None:
            health["data_written"] = gb(int(nvme["data_units_written"]) * 512_000)
        for source, target in (
            ("power_cycles", "power_cycles"),
            ("power_on_hours", "power_on_hours"),
            ("unsafe_shutdowns", "unsafe_shutdowns"),
            ("num_err_log_entries", "error_log_entries"),
            ("warning_temp_time", "minutes_over_warning_temp"),
        ):
            if nvme.get(source) is not None:
                health[target] = int(nvme[source])
        return health

    table = ((data.get("ata_smart_attributes") or {}).get("table")) or []
    if not isinstance(table, list):
        table = []
    passed = (data.get("smart_status") or {}).get("passed")
    if passed is None and not table and "temperature" not in data:
        return None

    def raw_value(*ids: int) -> int | None:
        for row in table:
            if row.get("id") in ids:
                return int(((row.get("raw") or {}).get("value")) or 0)
        return None

    def normalized(*ids: int) -> int | None:
        for row in table:
            if row.get("id") in ids and row.get("value") is not None:
                return int(row["value"])
        return None

    flags = []
    if passed is False:
        flags.append("the drive reports its reliability has degraded")
    pending = raw_value(197) or 0
    uncorrectable = raw_value(198) or 0
    reallocated = raw_value(5) or 0
    temperature = (data.get("temperature") or {}).get("current")
    if temperature is None:
        temperature = raw_value(194, 190)
    life_left = normalized(231, 177, 202, 233)
    percent_used = 0
    if life_left is not None:
        percent_used = max(0, 100 - life_left)
    health = blank_health(
        warning_flags=flags,
        temperature_c=temperature,
        percent_used=percent_used,
        media_errors=pending + uncorrectable,
        reallocated=reallocated,
        pending_sectors=pending,
        uncorrectable_sectors=uncorrectable,
        spare_known=False,
        percent_known=life_left is not None,
        media_known=True,
    )
    hours = raw_value(9)
    if hours is not None:
        health["power_on_hours"] = hours
    return health


WARRANTY_PAGES = (
    (("seagate", "maxtor", "lacie"), "Seagate", "https://www.seagate.com/support/warranty-and-replacements/"),
    (("adata", "xpg"), "ADATA", "https://www.adata.com/global/support/warranty/"),
    (("western digital", "sandisk", "wd"), "Western Digital", "https://support-en.wd.com/app/warrantystatusweb"),
    (("samsung",), "Samsung", "https://www.samsung.com/us/support/warranty/"),
    (("kingston",), "Kingston", "https://www.kingston.com/en/support"),
    (("crucial", "micron"), "Crucial", "https://www.crucial.com/support"),
    (("hynix",), "SK hynix", "https://ssd.skhynix.com/"),
    (("kioxia", "toshiba"), "Kioxia", "https://www.kioxia.com/en-us/support.html"),
)


def health_percent(health: dict) -> int | None:
    known = bool(
        health.get("percent_known")
        or health.get("media_errors")
        or health.get("reallocated")
        or health.get("warning_flags")
    )
    if not known:
        return None
    used = int(health.get("percent_used") or 0) if health.get("percent_known") else 0
    score = max(0, min(100, 100 - used))
    limited = bool(health.get("warning_flags") or health.get("media_errors") or health.get("reallocated"))
    if health.get("spare_known") and health.get("available_spare", 100) <= health.get("spare_threshold", 0):
        limited = True
    if limited:
        score = min(score, 10)
    return score


def performance_rating(read_ms, write_ms) -> tuple[str | None, str]:
    samples = []
    for value in (read_ms, write_ms):
        if value is None or value == "":
            continue
        samples.append(int(value))
    if not samples:
        return None, ""
    slowest = max(samples)
    if slowest < 50:
        level = "ok"
    elif slowest <= 250:
        level = "warning"
    else:
        level = "critical"
    return level, (
        f"Slowest response Windows has recorded: {slowest} ms. "
        "This is not the usual speed."
    )


def remaining_life_hours(percent_used, power_on_hours):
    if not percent_used or not power_on_hours:
        return None
    used = int(percent_used)
    hours = int(power_on_hours)
    if used <= 0 or used >= 100 or hours <= 0:
        return None
    return hours * (100 - used) / used


def warranty_lines(model: str, serial: str) -> list[str]:
    blob = (model or "").lower()
    maker = ""
    page = ""
    for keys, label, url in WARRANTY_PAGES:
        matched = False
        for key in keys:
            if key == "wd":
                matched = re.search(r"\bwd\b", blob) is not None
            else:
                matched = key in blob
            if matched:
                break
        if matched:
            maker, page = label, url
            break
    lines = ["  Warranty expiry: not stored on this drive."]
    if maker:
        lines.append(f"  Maker: {maker}")
    if model:
        lines.append(f"  Model: {model}")
    if serial:
        lines.append(f"  Serial: {serial}")
    if page:
        lines.append(f"  Warranty check: {page}")
    else:
        lines.append("  No warranty-check page is listed for this maker.")
    return lines


def forecast_lines(
    health_pct: int | None,
    performance: str | None,
    unsafe_shutdowns: int | None,
    worse: list[str],
    power_changed: bool,
    firmware_limited: bool,
) -> list[str]:
    notes = []
    if health_pct is not None and health_pct >= 90 and performance in ("warning", "critical"):
        notes.append(
            "The wear score is still high. The risk is the drive stopping in the middle of a read."
        )
    if unsafe_shutdowns is not None and int(unsafe_shutdowns) >= 20:
        notes.append(
            "That pattern matches the unexpected restarts already counted on this drive."
        )
    notes.extend(worse)
    if power_changed:
        notes.append("Since this Windows start, the power source changed.")
    if firmware_limited:
        notes.append("Since this Windows start, the processor was slowed by firmware.")
    if not notes:
        notes.append("The saved numbers do not show a new problem on this run.")
    return ["  What this means:", *[f"  - {note}" for note in notes]]


def worse_than(previous: dict | None, read_ms, media, temp_max) -> list[str]:
    if not previous:
        return []
    notes = []

    def older(key):
        value = previous.get(key)
        if value in (None, ""):
            return None
        return int(float(value))

    old_read = older("read_ms")
    if read_ms not in (None, "") and old_read is not None and int(read_ms) > old_read:
        notes.append(
            f"The slowest read is worse than the last saved check ({old_read} ms, now {int(read_ms)} ms)."
        )
    old_media = older("media")
    if media not in (None, "") and old_media is not None and int(media) > old_media:
        notes.append(f"Media errors increased from {old_media} to {int(media)}.")
    old_temp = older("temp_max")
    if temp_max not in (None, "") and old_temp is not None and int(temp_max) > old_temp:
        notes.append(
            f"The highest temperature is worse than the last saved check ({old_temp} C, now {int(temp_max)} C)."
        )
    return notes


def load_history() -> dict[str, dict]:
    if not HISTORY_PATH.is_file():
        return {}
    latest = {}
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        latest[parts[1]] = {
            "when": parts[0],
            "health": parts[2],
            "temp": parts[3],
            "temp_max": parts[4],
            "read_ms": parts[5],
            "media": parts[6],
        }
    return latest


def append_history(rows: list[dict]) -> None:
    if not rows:
        return
    with HISTORY_PATH.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                "\t".join(
                    [
                        row["when"],
                        str(row["drive"]),
                        "" if row.get("health") is None else str(row["health"]),
                        "" if row.get("temp") is None else str(row["temp"]),
                        "" if row.get("temp_max") is None else str(row["temp_max"]),
                        "" if row.get("read_ms") is None else str(row["read_ms"]),
                        "" if row.get("media") is None else str(row["media"]),
                    ]
                )
                + "\n"
            )


def hdd_temperature(level: str, reasons: list[str], spinning: bool, temp) -> tuple[str, list[str]]:
    if not spinning or temp is None or int(temp) < 50:
        return level, reasons
    reasons = [reason for reason in reasons if not reason.startswith("temperature is ")]
    reasons = [reason for reason in reasons if "does not report a failure" not in reason]
    reasons.append(f"temperature is {int(temp)} C")
    if int(temp) >= 80:
        return "critical", reasons
    if level == "ok":
        return "warning", reasons
    return level, reasons


def append_health(lines: list[str], health: dict, level: str, reasons: list[str], context: dict | None = None) -> dict:
    context = context or {}
    facts = []
    pct = health_percent(health)
    if pct is not None:
        lines.append(f"  Health: {pct}%")
        facts.append(("Health", f"{pct}%"))
    lines.append(f"  Result: {level.upper()}")
    facts.append(("Result", level.upper()))
    for reason in reasons:
        lines.append(f"  - {reason}")
    performance, performance_text = performance_rating(context.get("read_ms"), context.get("write_ms"))
    if performance:
        lines.append(f"  Performance: {performance.upper()}")
        lines.append(f"  - {performance_text}")
        facts.append(("Performance", performance.upper()))
        facts.append(("Slowest response", performance_text))
    temp_now = health.get("temperature_c")
    if temp_now is None:
        temp_now = context.get("temp_now")
    temp_max = context.get("temp_max")
    if temp_now is not None:
        lines.append(f"  Temperature now: {temp_now} C")
        facts.append(("Temperature now", f"{temp_now} C"))
    if temp_max is not None:
        lines.append(f"  Highest temperature: {temp_max} C")
        facts.append(("Highest temperature", f"{temp_max} C"))
    if health.get("minutes_over_warning_temp") == 0 and temp_max is not None:
        note = "The highest reading did not cross the drive's own warning temperature."
        lines.append(f"  {note}")
        facts.append(("Temperature limit", note))
    if health.get("spare_known"):
        spare = (
            f"{health['available_spare']}% (limit {health['spare_threshold']}%)"
        )
        lines.append(f"  Spare space: {spare}")
        facts.append(("Spare space", spare))
    if health.get("percent_known"):
        lines.append(f"  Life used: {health['percent_used']}%")
        facts.append(("Life used", f"{health['percent_used']}%"))
    hours = health.get("power_on_hours")
    if hours is not None:
        shown = f"{hours} hours ({int(hours) / 24:.1f} days)"
        lines.append(f"  Power-on time: {shown}")
        facts.append(("Power-on time", shown))
    remaining = remaining_life_hours(health.get("percent_used") if health.get("percent_known") else None, hours)
    if remaining is not None:
        estimate = f"{remaining:.0f} hours if future use matches the past"
        lines.append(f"  Remaining life estimate: {estimate}")
        facts.append(("Remaining life estimate", estimate))
    if health.get("media_known"):
        lines.append(f"  Media errors: {health['media_errors']}")
        facts.append(("Media errors", str(health["media_errors"])))
    for label, key in (
        ("Reallocated sectors", "reallocated"),
        ("Pending sectors", "pending_sectors"),
        ("Uncorrectable sectors", "uncorrectable_sectors"),
        ("Data read", "data_read"),
        ("Data written", "data_written"),
        ("Power cycles", "power_cycles"),
        ("Unsafe shutdowns", "unsafe_shutdowns"),
        ("Error-log entries", "error_log_entries"),
        ("Minutes over warning temperature", "minutes_over_warning_temp"),
        ("Minutes over critical temperature", "minutes_over_critical_temp"),
    ):
        if key == "reallocated" and not health.get(key):
            continue
        if key in health and health[key] is not None:
            lines.append(f"  {label}: {health[key]}")
            facts.append((label, str(health[key])))
    warranty = warranty_lines(str(context.get("model") or ""), str(context.get("serial") or ""))
    lines.extend(warranty)
    worse = context.get("worse") or []
    story = forecast_lines(
        pct,
        performance,
        health.get("unsafe_shutdowns"),
        worse,
        bool(context.get("power_changed")),
        bool(context.get("firmware_limited")),
    )
    lines.extend(story)
    return {
        "title": context.get("title") or context.get("model") or "Drive",
        "health_percent": pct,
        "level": level,
        "performance": performance,
        "facts": facts,
        "reasons": reasons,
        "forecast": [line[4:] for line in story if line.startswith("  - ")],
        "warranty": [line[2:] for line in warranty],
    }


def parse_hex_byte(token: str) -> int | None:
    token = token.strip().lower()
    if not token:
        return None
    try:
        return int(token, 16)
    except ValueError:
        return None


def life_band(value: int) -> str:
    low = max(0, (value - 1) * 10)
    high = value * 10
    return f"{low}-{high}%"


def android_health(life_text: str, eol_text: str) -> tuple[str, list[str], list[str]]:
    details = []
    level = "ok"
    reasons = []
    labels = ("type A", "type B")
    for index, token in enumerate(life_text.replace(",", " ").split()[:2]):
        value = parse_hex_byte(token)
        if value is None or value <= 0:
            continue
        band = life_band(value)
        details.append(f"Wear {labels[index]}: {band}")
        if value >= 10:
            level = "critical"
            reasons.append(f"wear {labels[index]} is {band}")
        elif value >= 8 and level == "ok":
            level = "warning"
            reasons.append(f"wear {labels[index]} is {band}")
    eol_token = eol_text.strip().split()[0] if eol_text.strip() else ""
    eol = parse_hex_byte(eol_token) if eol_token else None
    eol_name = {1: "normal", 2: "warning", 3: "urgent"}.get(eol or 0)
    if eol_name:
        details.append(f"Reserved blocks: {eol_name}")
    if eol == 3:
        level = "critical"
        reasons.append("reserved blocks are urgent")
    elif eol == 2:
        if level == "ok":
            level = "warning"
        reasons.append("reserved blocks are in warning")
    if not details:
        return "none", [], []
    if not reasons:
        reasons.append("the phone's storage health fields do not report a failure")
    return level, reasons, details


def win_error(prefix: str) -> OSError:
    code = ctypes.get_last_error()
    return OSError(code, f"{prefix}: {ctypes.WinError(code).strerror}")


def open_drive(number: int):
    kernel = load_kernel32()
    handle = kernel.CreateFileW(
        f"\\\\.\\PhysicalDrive{number}",
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == INVALID_HANDLE_VALUE or handle is None:
        err = ctypes.get_last_error()
        if err in (2, 3, 21):
            return None
        raise win_error(f"Open PhysicalDrive{number}")
    return handle


def query_protocol(handle, setup) -> bytes:
    kernel = load_kernel32()
    out_size = 8 + PROTOCOL_SIZE + HEALTH_LOG_SIZE
    buffer = ctypes.create_string_buffer(out_size)
    ctypes.c_uint32.from_buffer(buffer, 0).value = STORAGE_DEVICE_PROTOCOL_SPECIFIC_PROPERTY
    ctypes.c_uint32.from_buffer(buffer, 4).value = PROPERTY_STANDARD_QUERY
    proto = ProtocolData.from_buffer(buffer, 8)
    setup(proto)
    proto.ProtocolDataOffset = PROTOCOL_SIZE
    proto.ProtocolDataLength = HEALTH_LOG_SIZE
    returned = wintypes.DWORD()
    ok = kernel.DeviceIoControl(
        handle,
        IOCTL_STORAGE_QUERY_PROPERTY,
        buffer,
        8 + PROTOCOL_SIZE,
        buffer,
        out_size,
        ctypes.byref(returned),
        None,
    )
    if not ok:
        raise win_error("Read NVMe health log")
    raw = buffer.raw
    data_offset = 8 + int.from_bytes(raw[24:28], "little")
    length = int.from_bytes(raw[28:32], "little") or HEALTH_LOG_SIZE
    if data_offset < 0 or data_offset + 16 > len(raw):
        raise OSError("NVMe health log came back in an unexpected layout")
    return raw[data_offset : data_offset + min(length, HEALTH_LOG_SIZE)]


def cstring(blob: bytes, offset: int) -> str:
    if offset <= 0 or offset >= len(blob):
        return ""
    end = blob.find(b"\x00", offset)
    if end < 0:
        end = len(blob)
    return blob[offset:end].decode("ascii", errors="replace").strip()


def drive_identity(handle) -> dict:
    kernel = load_kernel32()
    out_size = 1024
    buffer = ctypes.create_string_buffer(out_size)
    ctypes.c_uint32.from_buffer(buffer, 0).value = STORAGE_DEVICE_PROPERTY
    ctypes.c_uint32.from_buffer(buffer, 4).value = PROPERTY_STANDARD_QUERY
    returned = wintypes.DWORD()
    ok = kernel.DeviceIoControl(
        handle,
        IOCTL_STORAGE_QUERY_PROPERTY,
        buffer,
        12,
        buffer,
        out_size,
        ctypes.byref(returned),
        None,
    )
    if not ok:
        raise win_error("Read drive name")
    raw = buffer.raw[: returned.value or out_size]
    return {
        "vendor": cstring(raw, int.from_bytes(raw[12:16], "little")),
        "product": cstring(raw, int.from_bytes(raw[16:20], "little")),
        "firmware": cstring(raw, int.from_bytes(raw[20:24], "little")),
        "serial": cstring(raw, int.from_bytes(raw[24:28], "little")),
        "bus": int.from_bytes(raw[28:32], "little"),
    }


def read_nvme_health(handle) -> dict:
    log = query_protocol(
        handle,
        lambda proto: (
            setattr(proto, "ProtocolType", PROTOCOL_TYPE_NVME),
            setattr(proto, "DataType", NVME_DATA_TYPE_LOG_PAGE),
            setattr(proto, "ProtocolDataRequestValue", NVME_LOG_PAGE_HEALTH),
            setattr(proto, "ProtocolDataRequestSubValue", 0),
        ),
    )
    return parse_health_log(log)


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "ssd-health-check"})
    with urllib.request.urlopen(request, timeout=120) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out)


def find_smartctl() -> str | None:
    names = ["smartctl.exe", "smartctl"] if sys.platform == "win32" else ["smartctl"]
    for name in names:
        direct = TOOLS / name
        if direct.is_file():
            return str(direct)
    if TOOLS.is_dir():
        for name in names:
            matches = [item for item in TOOLS.rglob(name) if item.is_file()]
            if matches:
                return str(matches[0])
    found = shutil.which("smartctl")
    if found:
        return found
    for candidate in (
        "/usr/local/sbin/smartctl",
        "/usr/local/bin/smartctl",
        "/opt/homebrew/bin/smartctl",
        "/usr/sbin/smartctl",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def seven_zip() -> str | None:
    for candidate in (
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return shutil.which("7z")


def service_exists(name: str) -> bool:
    completed = run_command(["sc", "query", name], timeout=20)
    return completed.returncode == 0


def copy_smartctl(found: Path) -> None:
    target = TOOLS / ("smartctl.exe" if found.suffix.lower() == ".exe" or sys.platform == "win32" else "smartctl")
    if found.resolve() == target.resolve():
        return
    TOOLS.mkdir(parents=True, exist_ok=True)
    shutil.copy2(found, target)
    if sys.platform != "win32":
        os.chmod(target, 0o755)


def install_smartctl_windows() -> None:
    TOOLS.mkdir(parents=True, exist_ok=True)
    setup = TOOLS / f"smartmontools-{SMARTCTL_VERSION}.win32-setup.exe"
    if not setup.is_file() or setup.stat().st_size < 100_000:
        print("Downloading smartctl...", flush=True)
        download(WIN_SMARTCTL_URL, setup)
    extracted = TOOLS / "smartmontools"
    zipper = seven_zip()
    if zipper:
        print("Extracting smartctl...", flush=True)
        run_command([zipper, "x", "-y", f"-o{extracted}", str(setup)], timeout=120)
    if find_smartctl():
        return
    print("Running the smartmontools installer into the tools folder...", flush=True)
    had_service = service_exists("smartd")
    dest = extracted if " " not in str(extracted) else Path(r"C:\smartmontools-health")
    dest.mkdir(parents=True, exist_ok=True)
    run_command([str(setup), "/S", f"/D={dest}"], timeout=180)
    if not had_service and service_exists("smartd"):
        run_command(["sc", "stop", "smartd"], timeout=20)
        run_command(["sc", "config", "smartd", "start=", "disabled"], timeout=20)
        run_command(["sc", "delete", "smartd"], timeout=20)


def install_smartctl_mac() -> None:
    TOOLS.mkdir(parents=True, exist_ok=True)
    image = TOOLS / f"smartmontools-{SMARTCTL_VERSION}.dmg"
    if not image.is_file() or image.stat().st_size < 100_000:
        print("Downloading smartctl...", flush=True)
        download(MAC_SMARTCTL_URL, image)
    mount = Path(tempfile.mkdtemp(prefix="ssd-health-dmg-"))
    attached = False
    try:
        run_command(
            ["hdiutil", "attach", "-nobrowse", "-mountpoint", str(mount), str(image)],
            timeout=120,
        )
        attached = True
        for candidate in mount.rglob("smartctl"):
            if candidate.is_file() and not candidate.is_symlink():
                copy_smartctl(candidate)
                return
        for package in mount.rglob("*.pkg"):
            expanded = Path(tempfile.mkdtemp(prefix="ssd-health-pkg-"))
            run_command(["pkgutil", "--expand", str(package), str(expanded)], timeout=120)
            for payload in expanded.rglob("Payload"):
                out = Path(tempfile.mkdtemp(prefix="ssd-health-payload-"))
                run_command(["tar", "-xf", str(payload), "-C", str(out)], timeout=120)
                for candidate in out.rglob("smartctl"):
                    if candidate.is_file():
                        copy_smartctl(candidate)
                        return
    finally:
        if attached:
            run_command(["hdiutil", "detach", str(mount)], timeout=60)


def ensure_smartctl() -> str:
    if find_smartctl():
        return ""
    try:
        if sys.platform == "win32":
            install_smartctl_windows()
        elif sys.platform == "darwin":
            install_smartctl_mac()
    except Exception as exc:
        return (
            f"smartctl could not be installed ({exc}). "
            "Built-in disk information is still shown."
        )
    found = find_smartctl()
    if found and Path(found).parent != TOOLS and (TOOLS / Path(found).name).is_file() is False:
        try:
            copy_smartctl(Path(found))
        except OSError:
            pass
    if find_smartctl():
        return ""
    return "smartctl could not be installed. Built-in disk information is still shown."


def smartctl_json(exe: str, args: list[str], timeout: int = 40) -> dict | None:
    try:
        completed = run_command([exe, *args], timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    text = decode_output(completed.stdout).strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def smartctl_devices(exe: str) -> list[dict]:
    data = smartctl_json(exe, ["--scan-open", "-j"], timeout=60) or {}
    return as_list(data.get("devices"))


def read_smart_device(exe: str, name: str, dtype: str | None) -> dict | None:
    args = ["-a", "-j"]
    if dtype and dtype not in ("auto", ""):
        args.extend(["-d", dtype])
    args.append(name)
    info = smartctl_json(exe, args)
    if not info:
        return None
    return health_from_smartctl(info)


def read_smart_for_number(exe: str | None, number: int, scanned: list[dict]) -> dict | None:
    if not exe:
        return None
    ordered = []
    for device in scanned:
        blob = json.dumps(device)
        if f"PhysicalDrive{number}" in blob or f"/dev/pd{number}" in blob:
            ordered.append(device)
    ordered.append({"name": f"/dev/pd{number}", "type": "auto"})
    letters = [
        device
        for device in scanned
        if re.fullmatch(r"/dev/sd[a-z]", str(device.get("name") or ""))
    ]
    if number < len(letters):
        ordered.append(letters[number])
    for device in scanned:
        name = str(device.get("name") or "")
        if name in (f"/dev/disk{number}", f"disk{number}"):
            ordered.append(device)
    ordered.append({"name": f"/dev/disk{number}", "type": "auto"})
    seen = set()
    for device in ordered:
        name = str(device.get("name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        health = read_smart_device(exe, name, device.get("type"))
        if health is not None:
            return health
    return None


def format_volume(vol: dict) -> str:
    letter = vol.get("Letter") or "(no drive letter)"
    filesystem = vol.get("FileSystem") or "unknown filesystem"
    state = " ".join(
        part for part in (vol.get("HealthStatus") or "", vol.get("OperationalStatus") or "") if part
    )
    free = gb(as_int(vol.get("Free")))
    size = gb(as_int(vol.get("Size")))
    label = f" {vol.get('Label')}" if vol.get("Label") else ""
    return f"  Volume: {letter}{label} {filesystem} {state}, free {free} of {size}".rstrip()


def chkdsk_scan(letter: str) -> str:
    try:
        completed = run_command(["chkdsk", letter, "/scan"], timeout=600)
    except subprocess.TimeoutExpired:
        return "The filesystem scan did not finish within 10 minutes."
    text = (decode_output(completed.stdout) + "\n" + decode_output(completed.stderr)).strip()
    tail = "\n".join(text.splitlines()[-12:])
    return tail or "The filesystem scan returned no output."


def windows_inventory() -> dict:
    path = Path(tempfile.gettempdir()) / "ssd-health-inventory.ps1"
    path.write_text(WINDOWS_INVENTORY, encoding="utf-8-sig")
    try:
        completed = run_command(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)],
            timeout=120,
        )
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    text = decode_output(completed.stdout)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        detail = text.strip() or decode_output(completed.stderr).strip() or "no disk list"
        raise OSError(detail)
    data = json.loads(text[start : end + 1])
    return data if isinstance(data, dict) else {}


def reliability_line(counter: dict) -> str:
    return (
        f"  Windows reliability: health {counter.get('HealthStatus')}, "
        f"temperature {counter.get('Temperature')} C, "
        f"highest {counter.get('TemperatureMax')} C, "
        f"wear {counter.get('Wear')}, "
        f"slowest read {counter.get('ReadLatencyMax')} ms, "
        f"slowest write {counter.get('WriteLatencyMax')} ms"
    )


def windows_scan(do_filesystem_scan: bool) -> tuple[str, int]:
    global REPORT_BLOCKS
    REPORT_BLOCKS = []
    lines = header()
    try:
        inventory = windows_inventory()
    except (OSError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        inventory = {}
        lines.append(f"Windows disk list could not be read ({exc}).")
        lines.append("")
    note = ensure_smartctl()
    if note:
        lines.append(note)
        lines.append("")
    exe = find_smartctl()
    scanned = smartctl_devices(exe) if exe else []
    disks = as_list(inventory.get("disks"))
    disk_map = {}
    for item in disks:
        if "Number" in item:
            disk_map[int(item["Number"])] = item
    counters = {}
    for item in as_list(inventory.get("reliability")):
        device_id = str(item.get("DeviceId") or "")
        if device_id:
            counters[device_id] = item
    worst = 0
    found = 0
    misses = 0
    history = load_history()
    history_rows = []
    power_changed, firmware_limited = windows_session_events()
    highest = max(disk_map) if disk_map else 0
    for number in range(32):
        info = disk_map.get(number)
        handle = None
        open_error = ""
        try:
            handle = open_drive(number)
        except OSError as exc:
            open_error = str(exc)
        if handle is None and info is None:
            misses += 1
            if misses >= 3 and number > highest:
                break
            continue
        misses = 0
        found += 1
        try:
            try:
                identity = drive_identity(handle) if handle else {}
            except OSError as exc:
                identity = {}
                open_error = open_error or str(exc)
            name = " ".join(
                part for part in (identity.get("vendor"), identity.get("product")) if part
            ).strip()
            if not name:
                name = (info or {}).get("FriendlyName") or f"PhysicalDrive{number}"
            lines.append(f"Drive {number}: {name}")
            if identity.get("serial"):
                lines.append(f"  Serial: {identity['serial']}")
            if identity.get("firmware"):
                lines.append(f"  Firmware: {identity['firmware']}")
            if info:
                bits = [
                    str(info.get("HealthStatus") or ""),
                    str(info.get("OperationalStatus") or ""),
                    str(info.get("BusType") or ""),
                    str(info.get("MediaType") or ""),
                ]
                lines.append("  Windows: " + " / ".join(bit for bit in bits if bit))
                if info.get("Size"):
                    lines.append(f"  Size: {gb(as_int(info.get('Size')))}")
            elif open_error:
                lines.append(f"  {open_error}")
            volumes = as_list((info or {}).get("Volumes"))
            for volume in volumes:
                lines.append(format_volume(volume))
                letter = str(volume.get("Letter") or "")
                if do_filesystem_scan and letter:
                    lines.append("  Filesystem scan:")
                    for scan_line in chkdsk_scan(letter).splitlines():
                        lines.append(f"  {scan_line}")
            if counters.get(str(number)):
                lines.append(reliability_line(counters[str(number)]))
            operational = str((info or {}).get("OperationalStatus") or "")
            bus = identity.get("bus")
            bus_name = str((info or {}).get("BusType") or "")
            health = None
            if "no media" in operational.lower():
                lines.append("  No disk is inserted.")
            else:
                if handle is not None and (bus == BUS_NVME or bus_name.lower() == "nvme"):
                    try:
                        health = read_nvme_health(handle)
                    except OSError as exc:
                        lines.append(f"  The NVMe health log could not be read ({exc}).")
                if health is None:
                    health = read_smart_for_number(exe, number, scanned)
                if health is not None:
                    counter = counters.get(str(number)) or {}
                    read_ms = counter.get("ReadLatencyMax")
                    write_ms = counter.get("WriteLatencyMax")
                    temp_max = counter.get("TemperatureMax")
                    spinning = str((info or {}).get("MediaType") or "").upper() == "HDD"
                    level, reasons = verdict(health)
                    level, reasons = hdd_temperature(
                        level, reasons, spinning, health.get("temperature_c")
                    )
                    media = health.get("media_errors") if health.get("media_known") else None
                    worse = worse_than(history.get(name), read_ms, media, temp_max)
                    worst = max(worst, RANK[level])
                    REPORT_BLOCKS.append(
                        append_health(
                            lines,
                            health,
                            level,
                            reasons,
                            {
                                "title": f"Drive {number}: {name}",
                                "model": name,
                                "serial": identity.get("serial") or "",
                                "read_ms": read_ms,
                                "write_ms": write_ms,
                                "temp_max": temp_max,
                                "worse": worse,
                                "power_changed": power_changed,
                                "firmware_limited": firmware_limited,
                            },
                        )
                    )
                    history_rows.append(
                        {
                            "when": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "drive": name,
                            "health": health_percent(health),
                            "temp": health.get("temperature_c"),
                            "temp_max": temp_max,
                            "read_ms": read_ms,
                            "media": media,
                        }
                    )
                else:
                    lines.append(f"  {NO_HEALTH_LOG}")
            lines.append("")
        finally:
            if handle is not None:
                load_kernel32().CloseHandle(handle)
    for phone in as_list(inventory.get("phones")):
        name = str(phone.get("FriendlyName") or "").strip()
        if name:
            found += 1
            if PHONE_NAME.search(name):
                lines.extend(phone_block(name))
            else:
                lines.extend(
                    [f"Portable device: {name}", f"  {PHONE_CABLE}", ""]
                )
    if not found:
        lines.append("No storage device could be opened.")
        worst = 3
    append_history(history_rows)
    return finish(lines), worst


def windows_session_events() -> tuple[bool, bool]:
    script = r"""
$boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime
$power = @(Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=105; StartTime=$boot} -ErrorAction SilentlyContinue)
$heat = @(Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Processor-Power'; Id=37; StartTime=$boot} -ErrorAction SilentlyContinue)
Write-Output ("POWER={0}" -f $(if ($power.Count) {1} else {0}))
Write-Output ("HEAT={0}" -f $(if ($heat.Count) {1} else {0}))
"""
    path = Path(tempfile.gettempdir()) / "ssd-health-events.ps1"
    path.write_text(script, encoding="utf-8-sig")
    try:
        completed = run_command(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)],
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False, False
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    text = decode_output(completed.stdout)
    return "POWER=1" in text, "HEAT=1" in text


def run_plist(args: list[str]) -> dict:
    try:
        completed = run_command(args, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return {}
    if not completed.stdout:
        return {}
    try:
        data = plistlib.loads(completed.stdout)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def collect_phone_names(node, found: list[str]) -> None:
    if isinstance(node, dict):
        name = str(node.get("_name") or "")
        if name and PHONE_NAME.search(name):
            found.append(name)
        for value in node.values():
            collect_phone_names(value, found)
    elif isinstance(node, list):
        for item in node:
            collect_phone_names(item, found)


def mac_phones() -> list[str]:
    try:
        completed = run_command(["system_profiler", "SPUSBDataType", "-json"], timeout=90)
    except (OSError, subprocess.SubprocessError):
        return []
    try:
        data = json.loads(decode_output(completed.stdout) or "{}")
    except json.JSONDecodeError:
        return []
    found: list[str] = []
    collect_phone_names(data, found)
    unique = []
    seen = set()
    for name in found:
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
    return unique


def mac_volume_line(part: dict, info: dict) -> str:
    name = info.get("VolumeName") or part.get("VolumeName") or part.get("DeviceIdentifier")
    mount = info.get("MountPoint") or part.get("MountPoint") or ""
    filesystem = (
        info.get("FilesystemName")
        or info.get("Content")
        or part.get("Content")
        or "unknown filesystem"
    )
    free = info.get("VolumeFreeSpace") or info.get("FreeSpace") or 0
    size = info.get("VolumeTotalSpace") or info.get("TotalSize") or info.get("Size") or part.get("Size") or 0
    place = f" mounted at {mount}" if mount else ""
    return (
        f"  Volume: {name}{place} {filesystem}, free {gb(as_int(free))} of {gb(as_int(size))}"
    )


def verify_volume(identifier: str) -> str:
    try:
        completed = run_command(["diskutil", "verifyVolume", identifier], timeout=600)
    except subprocess.TimeoutExpired:
        return "The filesystem scan did not finish within 10 minutes."
    text = (decode_output(completed.stdout) + "\n" + decode_output(completed.stderr)).strip()
    tail = "\n".join(text.splitlines()[-12:])
    return tail or "The filesystem scan returned no output."


def mac_scan(do_filesystem_scan: bool) -> tuple[str, int]:
    global REPORT_BLOCKS
    REPORT_BLOCKS = []
    lines = header()
    note = ensure_smartctl()
    if note:
        lines.append(note)
        lines.append("")
    exe = find_smartctl()
    scanned = smartctl_devices(exe) if exe else []
    listing = run_plist(["diskutil", "list", "-plist"])
    wholes = [str(item) for item in as_list(listing.get("WholeDisks"))]
    partitions = {}
    for item in as_list(listing.get("AllDisksAndPartitions")):
        if isinstance(item, dict) and item.get("DeviceIdentifier"):
            partitions[str(item["DeviceIdentifier"])] = item
    worst = 0
    found = 0
    history = load_history()
    history_rows = []
    if not wholes and not listing:
        lines.append("diskutil could not list the drives.")
        lines.append("")
    for disk in wholes:
        found += 1
        info = run_plist(["diskutil", "info", "-plist", disk])
        name = info.get("MediaName") or info.get("IORegistryEntryName") or disk
        lines.append(f"Drive {disk}: {name}")
        size = info.get("Size") or info.get("TotalSize") or info.get("DiskSize")
        if size:
            lines.append(f"  Size: {gb(as_int(size))}")
        if info.get("Protocol"):
            lines.append(f"  Protocol: {info.get('Protocol')}")
        if info.get("SolidState") is True:
            lines.append("  Media: SSD")
        elif info.get("SolidState") is False:
            lines.append("  Media: HDD")
        for part in as_list((partitions.get(disk) or {}).get("Partitions")):
            if not isinstance(part, dict):
                continue
            if not part.get("MountPoint") and not part.get("VolumeName"):
                continue
            identifier = str(part.get("DeviceIdentifier") or "")
            part_info = run_plist(["diskutil", "info", "-plist", identifier]) if identifier else {}
            lines.append(mac_volume_line(part, part_info))
            if do_filesystem_scan and (part_info.get("MountPoint") or part.get("MountPoint")):
                lines.append("  Filesystem scan:")
                for scan_line in verify_volume(identifier).splitlines():
                    lines.append(f"  {scan_line}")
        number_text = disk[4:] if disk.startswith("disk") else ""
        health = None
        if exe and number_text.isdigit():
            health = read_smart_for_number(exe, int(number_text), scanned)
            if health is None:
                direct = smartctl_json(exe, ["-a", "-j", f"/dev/{disk}"])
                if direct:
                    health = health_from_smartctl(direct)
        smart = str(info.get("SMARTStatus") or "")
        if health is not None:
            spinning = info.get("SolidState") is False
            level, reasons = verdict(health)
            level, reasons = hdd_temperature(
                level, reasons, spinning, health.get("temperature_c")
            )
            media = health.get("media_errors") if health.get("media_known") else None
            worse = worse_than(history.get(str(name)), None, media, None)
            worst = max(worst, RANK[level])
            REPORT_BLOCKS.append(
                append_health(
                    lines,
                    health,
                    level,
                    reasons,
                    {
                        "title": f"Drive {disk}: {name}",
                        "model": str(name),
                        "serial": str(info.get("DeviceSerialNumber") or info.get("SerialNumber") or ""),
                        "worse": worse,
                    },
                )
            )
            history_rows.append(
                {
                    "when": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "drive": str(name),
                    "health": health_percent(health),
                    "temp": health.get("temperature_c"),
                    "temp_max": None,
                    "read_ms": None,
                    "media": media,
                }
            )
        elif smart.lower() == "verified":
            lines.append("  Result: OK")
            lines.append("  - the drive's own health log does not report a failure")
            lines.append(f"  SMART status: {smart}")
        elif smart.lower() == "failing":
            worst = max(worst, RANK["critical"])
            lines.append("  Result: CRITICAL")
            lines.append("  - the drive reports its reliability has degraded")
            lines.append(f"  SMART status: {smart}")
        else:
            lines.append(f"  {NO_HEALTH_LOG}")
            if smart:
                lines.append(f"  SMART status: {smart}")
        lines.append("")
    for name in mac_phones():
        found += 1
        lines.extend(phone_block(name))
    if not found:
        lines.append("No storage device could be opened.")
        worst = 3
    append_history(history_rows)
    return finish(lines), worst


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def space_line(path: str) -> str | None:
    try:
        stats = os.statvfs(path)
    except (OSError, AttributeError):
        return None
    total = stats.f_frsize * stats.f_blocks
    free = stats.f_frsize * stats.f_bavail
    if total <= 0:
        return None
    return f"  Free space: {gb(free)} of {gb(total)} ({path})"


def android_scan() -> tuple[str, int]:
    lines = header()
    worst = 0
    saw = False
    root = Path("/sys/block")
    if root.is_dir():
        for block in sorted(root.iterdir()):
            if block.name.startswith(("loop", "ram", "zram", "dm-")):
                continue
            device = block / "device"
            life = read_text(device / "life_time") if device.is_dir() else ""
            eol = read_text(device / "pre_eol_info") if device.is_dir() else ""
            model = ""
            if device.is_dir():
                model = read_text(device / "name") or read_text(device / "model")
            interesting = block.name.startswith(("mmc", "sd", "nvme")) or bool(life or eol)
            if not interesting:
                continue
            saw = True
            lines.append(f"Storage: {model or block.name}")
            level, reasons, details = android_health(life, eol)
            if level == "none":
                lines.append("  This phone does not expose a storage health log.")
            else:
                worst = max(worst, RANK[level])
                lines.append(f"  Result: {level.upper()}")
                for reason in reasons:
                    lines.append(f"  - {reason}")
                for detail in details:
                    lines.append(f"  {detail}")
            lines.append("")
    space = None
    for path in ("/storage/emulated/0", "/sdcard", "/data", "/"):
        space = space_line(path)
        if space:
            break
    if space:
        lines.append("Phone storage")
        lines.append(space)
        if not saw:
            lines.append("  This phone does not expose a storage health log.")
        lines.append("")
    elif not saw:
        lines.append("This phone does not expose a storage health log.")
        lines.append("")
        worst = 3
    return finish(lines), worst


def ios_report() -> tuple[str, int]:
    lines = header()
    lines.append(
        "This iPhone cannot run a drive health check. "
        "Apple does not allow a program to read the phone's storage health."
    )
    lines.append("")
    return finish(lines), 3


def other_report() -> tuple[str, int]:
    lines = header()
    lines.append(
        "This system cannot read a drive health log. "
        "Run this program on Windows, Mac, or Android in Termux. "
        "A stock iPhone does not allow it."
    )
    lines.append("")
    return finish(lines), 3


def render_html(report_text: str) -> str:
    cards = []
    for block in REPORT_BLOCKS:
        percent = block.get("health_percent")
        percent_text = "Not available" if percent is None else f"{percent}%"
        level = str(block.get("level") or "")
        facts = "".join(
            "<div class=\"fact\"><span>{0}</span><strong>{1}</strong></div>".format(
                html.escape(label), html.escape(value)
            )
            for label, value in block.get("facts") or []
        )
        reasons = "".join(f"<li>{html.escape(item)}</li>" for item in block.get("reasons") or [])
        story = "".join(f"<li>{html.escape(item)}</li>" for item in block.get("forecast") or [])
        warranty = "".join(f"<p>{html.escape(item)}</p>" for item in block.get("warranty") or [])
        cards.append(
            "<article>"
            f"<h2>{html.escape(str(block.get('title') or 'Drive'))}</h2>"
            f"<p class=\"score\">{html.escape(percent_text)}</p>"
            f"<p class=\"level {html.escape(level)}\">{html.escape(level.upper())}</p>"
            f"<div class=\"facts\">{facts}</div>"
            f"<ul>{reasons}</ul>"
            "<h3>What this means</h3>"
            f"<ul>{story}</ul>"
            "<h3>Warranty</h3>"
            f"{warranty}"
            "</article>"
        )
    body = "\n".join(cards) or f"<pre>{html.escape(report_text)}</pre>"
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{PRODUCT_NAME}</title><style>"
        "body{font-family:Georgia,serif;margin:0;background:#f4f1ea;color:#1c1915}"
        "header,main{max-width:46rem;margin:0 auto;padding:1.5rem}"
        "article{background:#fff;border:1px solid #ddd6c8;padding:1.4rem;margin:1rem 0}"
        ".score{font-size:3rem;margin:0}"
        ".level.ok{color:#1f6b3a}.level.warning{color:#8a5a00}.level.critical{color:#8d1d1d}"
        ".fact{display:flex;justify-content:space-between;gap:1rem;padding:.4rem 0;border-bottom:1px solid #eee}"
        "</style></head><body><header><h1>"
        f"{PRODUCT_NAME}</h1><p>This page is on this computer. It is not uploaded.</p>"
        f"</header><main>{body}</main></body></html>"
    )


def serve_page(page: str) -> str:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            data = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            return

    for port in (80, 8765):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        except OSError:
            continue
        threading.Thread(target=server.serve_forever, daemon=True).start()
        if port == 80:
            return "http://127.0.0.1/"
        return f"http://127.0.0.1:{port}/"
    return ""


def scan(do_filesystem_scan: bool) -> tuple[str, int]:
    global REPORT_BLOCKS
    REPORT_BLOCKS = []
    kind = host_kind()
    if kind == "ios":
        return ios_report()
    if kind == "android":
        return android_scan()
    if kind == "mac":
        return mac_scan(do_filesystem_scan)
    if kind == "windows":
        return windows_scan(do_filesystem_scan)
    return other_report()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    kind = host_kind()
    if kind == "windows" and not is_admin():
        elevate_and_exit()
    if kind == "mac" and hasattr(os, "geteuid") and os.geteuid() != 0:
        os.execvp("sudo", ["sudo", "--", sys.executable, *args])
    try:
        report, code = scan("--scan" in args)
    except OSError as exc:
        report = f"Drive health check failed.\n{exc}\n"
        code = 3
    REPORT_PATH.write_text(report, encoding="utf-8")
    page = render_html(report)
    PAGE_PATH.write_text(page, encoding="utf-8")
    print(report, end="")
    if "--no-browser" not in args:
        url = serve_page(page)
        if url:
            print(f"Report page: {url}")
            try:
                webbrowser.open(url)
            except OSError:
                pass
    if "--serve" in args:
        threading.Event().wait()
    elif "--no-wait" not in args and sys.stdin is not None and sys.stdin.isatty():
        try:
            input("Press Enter to close.")
        except EOFError:
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(main())
