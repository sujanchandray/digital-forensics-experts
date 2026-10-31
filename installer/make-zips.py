"""Build the Windows and Mac download archives. Not part of the health check."""

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)

WINDOWS = [
    "StorageHealthCheck-Setup.cmd",
    "installer/Install-StorageHealthCheck.ps1",
    "ssd_health.py",
    "tools/smartctl.exe",
    "tools/COPYING.txt",
]
MAC = [
    "ssd_health.py",
    "check-ssd-health.command",
]


def pack(name: str, names: list[str]) -> None:
    dest = DIST / name
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in names:
            path = ROOT / item
            data = path.read_bytes().replace(b"\r\n", b"\n") if item.endswith(".command") else path.read_bytes()
            archive.writestr(item.replace("\\", "/"), data)
    print(dest)


if __name__ == "__main__":
    pack("StorageHealthCheck-Windows.zip", WINDOWS)
    pack("StorageHealthCheck-Mac.zip", MAC)
