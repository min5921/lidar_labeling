@echo off
setlocal

for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] The project virtual environment was not found.
    echo Run launchers\windows\setup_windows.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m lidar_label_tool calibrate %*
if errorlevel 1 (
    echo.
    echo [ERROR] LiDAR Camera Calibration Editor exited with an error.
    echo See docs\USER_MANUAL.md for supported dataset and calibration formats.
    pause
    exit /b 1
)
