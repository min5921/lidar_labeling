@echo off
setlocal
cd /d "%~dp0\..\.."

if not exist ".venv\Scripts\lidar-label-tool.exe" (
    echo [ERROR] Project virtual environment was not found.
    pause
    exit /b 1
)

for /f "usebackq delims=" %%I in (`".venv\Scripts\python.exe" scripts\convert_one_chip_dataset.py --print-default output`) do set "DATASET=%%I"
if not "%~1"=="" set "DATASET=%~1"

".venv\Scripts\lidar-label-tool.exe" stats "%DATASET%"
pause
