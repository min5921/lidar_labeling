@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_windows.ps1" %*
if errorlevel 1 (
    echo.
    echo [ERROR] Environment setup failed. See docs\31_LAB_SOURCE_SETUP.md.
    pause
    exit /b 1
)

echo.
echo Setup completed. Run run_windows.bat to start LiDAR Label Tool.
pause
