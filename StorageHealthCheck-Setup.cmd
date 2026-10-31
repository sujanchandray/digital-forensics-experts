@echo off
cd /d "%~dp0"
if exist "%~dp0Install-StorageHealthCheck.ps1" (
  set "SCRIPT=%~dp0Install-StorageHealthCheck.ps1"
) else (
  set "SCRIPT=%~dp0installer\Install-StorageHealthCheck.ps1"
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0' -File | Unblock-File -ErrorAction SilentlyContinue"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
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
