@echo off
setlocal
set "SCRIPT=%~dp0ssd_health.py"

call :find
if defined PYTHON goto run

echo Python 3 was not found. Installing it with winget.
winget install --id Python.Python.3.12 -e --scope user --accept-package-agreements --accept-source-agreements
call :find
if defined PYTHON goto run

echo Install Python 3 from https://www.python.org/downloads/ and run this again.
pause
exit /b 1

:run
"%PYTHON%" "%SCRIPT%" %*
exit /b %ERRORLEVEL%

:find
set "PYTHON="
where py >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYTHON=%%P"
  if defined PYTHON exit /b 0
)
for %%P in (
  "%LocalAppData%\Programs\Python\Python313\python.exe"
  "%LocalAppData%\Programs\Python\Python312\python.exe"
  "%ProgramFiles%\Python313\python.exe"
  "%ProgramFiles%\Python312\python.exe"
) do (
  if exist %%P (
    set "PYTHON=%%~P"
    exit /b 0
  )
)
where python >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do (
    echo %%P | find /I "WindowsApps" >nul
    if errorlevel 1 set "PYTHON=%%P"
  )
  if defined PYTHON exit /b 0
)
exit /b 1
