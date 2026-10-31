$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$stage = Join-Path $root "dist\setup-stage"
$dist = Join-Path $root "dist"
$target = Join-Path $dist "QuickStorageHealthCheck-Setup.cmd"
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Get-ChildItem -LiteralPath $stage -Force | Remove-Item -Recurse -Force
if (Test-Path $target) { Remove-Item -Force $target }

Copy-Item -Force (Join-Path $root "installer\Install-StorageHealthCheck.ps1") $stage
Copy-Item -Force (Join-Path $root "ssd_health.py") $stage
Copy-Item -Force (Join-Path $root "tools\smartctl.exe") $stage
Copy-Item -Force (Join-Path $root "tools\COPYING.txt") $stage

$zip = Join-Path $dist "setup-payload.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip
$payload = [Convert]::ToBase64String([IO.File]::ReadAllBytes($zip))
$wrapped = [regex]::Replace($payload, ".{76}", "$&`r`n")

$header = @'
@echo off
setlocal
set "QSHC_SRC=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$src=$env:QSHC_SRC; $raw=[IO.File]::ReadAllText($src); $mark='###QSHC-PAYLOAD###'; $i=$raw.LastIndexOf($mark); if($i -lt 0){ throw 'Setup file is incomplete.' }; $b64=($raw.Substring($i+$mark.Length) -replace '\s',''); $bytes=[Convert]::FromBase64String($b64); $dest=Join-Path $env:TEMP ('QuickStorageHealthCheck-' + [guid]::NewGuid().ToString('n')); [void](New-Item -ItemType Directory -Force -Path $dest); $zip=Join-Path $dest 'payload.zip'; [IO.File]::WriteAllBytes($zip,$bytes); Expand-Archive -Force -Path $zip -DestinationPath $dest; foreach($f in (Get-ChildItem -LiteralPath $dest -File)){ Unblock-File -LiteralPath $f.FullName -ErrorAction SilentlyContinue }; & (Join-Path $dest 'Install-StorageHealthCheck.ps1'); if(-not $?){ exit 1 }"
if errorlevel 1 goto failed
echo.
echo Setup finished. Approve the administrator prompt if Windows asks.
echo The report opens in the browser on this computer.
ping -n 9 127.0.0.1 >nul
exit /b 0
:failed
echo.
echo Setup did not finish.
pause
exit /b 1
###QSHC-PAYLOAD###
'@

Set-Content -Path $target -Value ($header.TrimEnd() + "`r`n" + $wrapped) -Encoding ASCII
Remove-Item -Force $zip
Write-Output $target
Get-Item $target | Select-Object FullName, Length
