@echo off
setlocal

for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\scripts\setup_windows.ps1" %*
if errorlevel 1 (
    echo.
    echo [ERROR] Environment setup failed. See docs\31_LAB_SOURCE_SETUP.md.
    pause
    exit /b 1
)

echo.
echo Setup completed.
echo Run launchers\windows\run_windows.bat for labeling or launchers\windows\run_calibration.bat for calibration editing.
pause
