$ErrorActionPreference = "Stop"
$ready = Join-Path $env:TEMP "QuickStorageHealthCheck.ready"
$pidFile = Join-Path $env:TEMP "QuickStorageHealthCheck.pid"
if (Test-Path $ready) { Remove-Item -Force $ready }
if (Test-Path $pidFile) { Remove-Item -Force $pidFile }
$env:QSHC_READY = $ready
& (Join-Path $PSScriptRoot "Install-StorageHealthCheck.ps1")
$deadline = (Get-Date).AddMinutes(4)
while ((Get-Date) -lt $deadline) {
    if (Test-Path $ready) { exit 0 }
    if (Test-Path $pidFile) {
        $procId = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($procId -and -not (Get-Process -Id $procId -ErrorAction SilentlyContinue)) { exit 1 }
    }
    Start-Sleep -Milliseconds 400
}
exit 1
