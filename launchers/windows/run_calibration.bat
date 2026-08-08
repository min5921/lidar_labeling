@echo off
setlocal

for %%I in ("%~dp0..\..") do set "PROJECT_ROOT=%%~fI"
cd /d "%PROJECT_ROOT%"

set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0"
set "CONDA_PREFIX="
set "CONDA_DEFAULT_ENV="
set "CONDA_PROMPT_MODIFIER="
set "CONDA_SHLVL="
set "PYTHONHOME="
set "PYTHONPATH="
set "QT_PLUGIN_PATH="
set "QML2_IMPORT_PATH="

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] The project virtual environment was not found.
    echo Run launchers\windows\setup_windows.bat first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" scripts\verify_source_environment.py
if errorlevel 1 (
    echo.
    echo [ERROR] The Python/Qt environment is incomplete or damaged.
    echo Run launchers\windows\setup_windows.bat -Repair first.
    echo If repair fails, run launchers\windows\setup_windows.bat -Recreate.
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
