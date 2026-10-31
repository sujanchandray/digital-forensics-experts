$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dest = Join-Path $env:LOCALAPPDATA "Storage Health Check"
$tools = Join-Path $dest "tools"
New-Item -ItemType Directory -Force -Path $tools | Out-Null
Copy-Item -Force (Join-Path $root "ssd_health.py") $dest
$smartctl = Join-Path $root "tools\smartctl.exe"
if (Test-Path $smartctl) {
    Copy-Item -Force $smartctl (Join-Path $tools "smartctl.exe")
}
foreach ($copying in @(
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
    $python = & py -3 -c "import sys; print(sys.executable)"
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

$shortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Storage Health Check.lnk"
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcut)
$link.TargetPath = $python
$link.Arguments = "`"$dest\ssd_health.py`""
$link.WorkingDirectory = $dest
$link.Description = "Storage Health Check"
$link.Save()
Write-Output "Storage Health Check is in the Start menu."
Write-Output "Open it, approve the administrator prompt, and the report opens in the browser on this computer."
