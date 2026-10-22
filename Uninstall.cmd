@echo off
setlocal
cd /d "%~dp0"
echo ===================================================
echo   QuickMorph - Uninstall
echo ===================================================
echo.
set "PY="
where py >nul 2>&1 && py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY (
    echo [ERROR] Python was not found - delete %%LOCALAPPDATA%%\QuickMorph by hand and remove
    echo         HKCU\Software\Classes\*\shell\QuickMorph.View / QuickMorph.Save with regedit.
    pause
    exit /b 1
)

%PY% install.py --uninstall %*
if errorlevel 1 (
    echo.
    echo [ERROR] Uninstall failed.
    pause
    exit /b 1
)
echo.
pause
