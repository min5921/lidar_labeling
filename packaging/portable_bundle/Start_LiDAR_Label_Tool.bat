@echo off
setlocal
cd /d "%~dp0"

set "EXE=%~dp0LiDARLabelTool.exe"

if not exist "%EXE%" (
    echo [ERROR] LiDARLabelTool.exe was not found.
    echo Keep this launcher next to LiDARLabelTool.exe and the _internal folder.
    pause
    exit /b 1
)

if not "%~1"=="" (
    start "" "%EXE%" "%~1"
    exit /b 0
)

set "DATASET="
set "MULTIPLE_DATASETS="
for /d %%D in ("%~dp0datasets\*") do (
    if exist "%%~fD\dataset.json" (
        if defined DATASET (
            set "MULTIPLE_DATASETS=1"
        ) else (
            set "DATASET=%%~fD"
        )
    )
)

if defined DATASET if not defined MULTIPLE_DATASETS (
    start "" "%EXE%" "%DATASET%"
) else (
    start "" "%EXE%"
)
