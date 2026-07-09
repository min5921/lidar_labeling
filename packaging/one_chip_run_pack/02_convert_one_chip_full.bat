@echo off
setlocal
cd /d "%~dp0\..\.."

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Project virtual environment was not found.
    pause
    exit /b 1
)

for /f "usebackq delims=" %%I in (`".venv\Scripts\python.exe" scripts\convert_one_chip_dataset.py --print-default source`) do set "SOURCE=%%I"
for /f "usebackq delims=" %%I in (`".venv\Scripts\python.exe" scripts\convert_one_chip_dataset.py --print-default output`) do set "OUTPUT=%%I"
if not "%~1"=="" set "OUTPUT=%~1"

if not exist "%SOURCE%\rosbags" (
    echo [ERROR] Source rosbags were not found.
    echo Expected: %SOURCE%\rosbags
    pause
    exit /b 1
)

if exist "%OUTPUT%" (
    echo [ERROR] Output already exists. The converter will not overwrite data.
    echo Rename or back up this folder first:
    echo %OUTPUT%
    pause
    exit /b 1
)

if not "%~1"=="" (
    ".venv\Scripts\python.exe" scripts\convert_one_chip_dataset.py --output "%OUTPUT%"
) else (
    ".venv\Scripts\python.exe" scripts\convert_one_chip_dataset.py
)

if errorlevel 1 (
    echo.
    echo [ERROR] Conversion failed.
    pause
    exit /b 1
)

echo.
echo Conversion finished. Running preflight...
".venv\Scripts\lidar-label-tool.exe" preflight "%OUTPUT%"
pause
