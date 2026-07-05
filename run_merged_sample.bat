@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Project Python environment was not found.
    pause
    exit /b 1
)

if not exist "local_data\incoming\merged_device_full\dataset.json" (
    echo [ERROR] Converted merged dataset was not found.
    echo Expected: local_data\incoming\merged_device_full
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m lidar_label_tool gui ^
  "local_data\incoming\merged_device_full"

if errorlevel 1 pause
