@echo off
setlocal
cd /d "%~dp0"

rem User-editable dataset path. The folder must contain dataset.json.
set "DATASET={{DEFAULT_DATASET_PATH}}"
set "EXE=%~dp0LiDARLabelTool.exe"

if not exist "%EXE%" (
    echo [ERROR] LiDARLabelTool.exe was not found.
    pause
    exit /b 1
)

if not exist "%DATASET%\dataset.json" (
    echo [ERROR] Dataset was not found:
    echo %DATASET%
    echo.
    echo Edit DATASET in this file, or drag a dataset folder onto
    echo Start_LiDAR_Label_Tool.bat.
    pause
    exit /b 1
)

start "" "%EXE%" "%DATASET%"
