$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (Test-Path (Join-Path $here "ssd_health.py")) {
    $root = $here
} else {
    $root = Split-Path -Parent (Split-Path -Parent $here)
}
$dest = Join-Path $env:LOCALAPPDATA "QuickStorageHealthCheck"
$tools = Join-Path $dest "tools"
New-Item -ItemType Directory -Force -Path $tools | Out-Null
Copy-Item -Force (Join-Path $root "ssd_health.py") $dest
$smartctl = Join-Path $root "tools\smartctl.exe"
if (-not (Test-Path $smartctl)) {
    $smartctl = Join-Path $root "smartctl.exe"
}
if (Test-Path $smartctl) {
    Copy-Item -Force $smartctl (Join-Path $tools "smartctl.exe")
}
foreach ($copying in @(
    (Join-Path $root "COPYING.txt"),
    (Join-Path $root "tools\COPYING.txt"),
    (Join-Path $root "tools\smartmontools\doc\COPYING.txt")
)) {
    if (Test-Path $copying) {
        Copy-Item -Force $copying (Join-Path $tools "COPYING.txt")
        break
    }
}

$python = $null
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    $out = Join-Path $env:TEMP "qshc-python-path.txt"
    if (Test-Path $out) { Remove-Item -Force $out }
    Start-Process -FilePath $py.Source -ArgumentList "-3","-c","import sys; print(sys.executable)" -WindowStyle Hidden -Wait -RedirectStandardOutput $out | Out-Null
    if (Test-Path $out) {
        $python = (Get-Content -LiteralPath $out -ErrorAction SilentlyContinue | Select-Object -First 1)
        if ($python) { $python = $python.Trim() }
    }
}
if (-not $python -or -not (Test-Path $python)) {
    $embed = Join-Path $dest "python"
    $python = Join-Path $embed "python.exe"
    if (-not (Test-Path $python)) {
        New-Item -ItemType Directory -Force -Path $embed | Out-Null
        $zip = Join-Path $env:TEMP "python-3.12.10-embed-amd64.zip"
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip" -OutFile $zip
        Expand-Archive -Force -Path $zip -DestinationPath $embed
    }
}
$pythonw = Join-Path (Split-Path -Parent $python) "pythonw.exe"
if (Test-Path $pythonw) { $python = $pythonw }

$shortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\QuickStorageHealthCheck.lnk"
$oldShortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Storage Health Check.lnk"
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcut)
$link.TargetPath = $python
$link.Arguments = "`"$dest\ssd_health.py`""
$link.WorkingDirectory = $dest
$link.Description = "QuickStorageHealthCheck"
$link.Save()
if ((Test-Path $oldShortcut) -and ($oldShortcut -ne $shortcut)) {
    Remove-Item -Force $oldShortcut
}
$ready = Join-Path $env:TEMP "QuickStorageHealthCheck.ready"
$proc = Start-Process -FilePath $python -ArgumentList @("`"$dest\ssd_health.py`"","--ready",$ready) -WorkingDirectory $dest -WindowStyle Hidden -PassThru
Set-Content -Path (Join-Path $env:TEMP "QuickStorageHealthCheck.pid") -Value $proc.Id -Encoding ASCII
