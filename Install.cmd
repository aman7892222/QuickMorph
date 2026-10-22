@echo off
setlocal
cd /d "%~dp0"
echo ===================================================
echo   QuickMorph - Right-Click PDF Installer
echo ===================================================
echo.
set "PY="
where py >nul 2>&1 && py -3 -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>&1 && set "PY=python"
if not defined PY (
    echo [ERROR] Python 3.9 or newer was not found.
    echo         Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^),
    echo         then double-click Install.cmd again.
    pause
    exit /b 1
)

%PY% install.py %*
if errorlevel 1 (
    echo.
    echo [ERROR] Installation failed. See the messages above.
    pause
    exit /b 1
)
echo.
pause
