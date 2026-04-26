@echo off
REM ============================================================================
REM  DBD Auto Skill Check - Start
REM  --------------------------------------------------------------------------
REM  Launches the Flask UI on http://127.0.0.1:7860 using the venv created by
REM  setup.bat, then opens the page in your default browser.
REM
REM  If you haven't run setup.bat yet, this script will tell you to.
REM ============================================================================

REM ── Auto-elevate to Administrator ────────────────────────────────────────
REM CPU temperature and CPU package power require loading LibreHardwareMonitor's
REM signed kernel driver, which only works inside an elevated process. We probe
REM the current token via `net session` (returns 0 only when admin) and, if
REM not elevated, relaunch ourselves via UAC's RunAs verb. If the user clicks
REM "No" on the UAC prompt, PowerShell raises and this instance just exits.
net session >nul 2>&1
if errorlevel 1 (
    echo Requesting Administrator rights ^(needed for CPU temp/power sensors^)...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

setlocal EnableExtensions
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "HOST=127.0.0.1"
set "PORT=7860"
set "URL=http://%HOST%:%PORT%"

if not exist "%VENV_PY%" (
    echo.
    echo [ERROR] Virtual environment not found.
    echo         Run setup.bat first to install dependencies.
    echo.
    pause
    exit /b 1
)

if not exist "app_flask.py" (
    echo.
    echo [ERROR] app_flask.py not found in this directory.
    echo         Make sure start.bat sits next to app_flask.py.
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================================
echo   Starting DBD Auto Skill Check on %URL%
echo ============================================================================
echo.

REM Open the browser tab a moment after the server starts. `start ""` returns
REM immediately so the server (next line) keeps the console.
start "" /b cmd /c "timeout /t 3 /nobreak >nul && start "" "%URL%""

"%VENV_PY%" app_flask.py --host %HOST% --port %PORT%
set "EXITCODE=%ERRORLEVEL%"

echo.
echo Server exited with code %EXITCODE%.
pause
endlocal & exit /b %EXITCODE%
