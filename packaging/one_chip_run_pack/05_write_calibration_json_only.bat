@echo off
setlocal
cd /d "%~dp0\..\.."

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Project virtual environment was not found.
    pause
    exit /b 1
)

for /f "usebackq delims=" %%I in (`".venv\Scripts\python.exe" scripts\convert_one_chip_dataset.py --print-default calibration-output`) do set "OUTPUT=%%I"
if not "%~1"=="" set "OUTPUT=%~1"

if exist "%OUTPUT%" (
    echo [ERROR] Output already exists:
    echo %OUTPUT%
    pause
    exit /b 1
)

".venv\Scripts\python.exe" scripts\convert_one_chip_dataset.py ^
  --calibration-only ^
  --output "%OUTPUT%"

if errorlevel 1 (
    echo.
    echo [ERROR] Calibration conversion failed.
    pause
    exit /b 1
)

echo.
echo Created: %OUTPUT%
pause
