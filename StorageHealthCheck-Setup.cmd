@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\Install-StorageHealthCheck.ps1"
if errorlevel 1 pause
exit /b %ERRORLEVEL%
