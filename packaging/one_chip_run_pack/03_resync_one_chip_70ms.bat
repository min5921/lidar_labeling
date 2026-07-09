@echo off
setlocal
cd /d "%~dp0\..\.."

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Project virtual environment was not found.
    pause
    exit /b 1
)

for /f "usebackq delims=" %%I in (`".venv\Scripts\python.exe" scripts\convert_one_chip_dataset.py --print-default output`) do set "DATASET=%%I"
if not "%~1"=="" set "DATASET=%~1"

if not exist "%DATASET%\dataset.json" (
    echo [ERROR] Converted dataset was not found.
    echo Expected: %DATASET%\dataset.json
    pause
    exit /b 1
)

".venv\Scripts\python.exe" scripts\convert_one_chip_dataset.py ^
  --output "%DATASET%" ^
  --sync-only-existing

if errorlevel 1 (
    echo.
    echo [ERROR] Resync failed.
    pause
    exit /b 1
)

echo.
echo Resync finished. Running preflight...
".venv\Scripts\lidar-label-tool.exe" preflight "%DATASET%"
pause
