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
