@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] The project virtual environment was not found.
    echo Run setup_windows.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m lidar_label_tool gui %*
if errorlevel 1 (
    echo.
    echo [ERROR] LiDAR Label Tool exited with an error.
    echo Run scripts\verify_source_environment.py or see docs\31_LAB_SOURCE_SETUP.md.
    pause
    exit /b 1
)
