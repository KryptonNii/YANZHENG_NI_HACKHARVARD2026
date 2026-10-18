@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist "%~dp0api\.venv\Scripts\python.exe" (
    echo TrialPilot API environment is missing: api\.venv\Scripts\python.exe
    echo Install the prepared API dependencies, then run sysup.cmd again.
    pause
    exit /b 1
)

"%~dp0api\.venv\Scripts\python.exe" "%~dp0scripts\start_services.py" %*
set "TP_EXIT=%ERRORLEVEL%"
if not "%TP_EXIT%"=="0" (
    echo.
    echo Startup needs attention. Read the message above; existing services were not stopped.
    pause
) else (
    timeout /t 4 /nobreak >nul 2>nul
)
exit /b %TP_EXIT%
