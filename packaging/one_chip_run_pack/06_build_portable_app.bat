@echo off
setlocal
cd /d "%~dp0\..\.."

if not exist "packaging\build_windows_portable.ps1" (
    echo [ERROR] Portable build script was not found.
    pause
    exit /b 1
)

powershell -ExecutionPolicy Bypass -File packaging\build_windows_portable.ps1
if errorlevel 1 (
    echo.
    echo [ERROR] Portable build failed.
    pause
    exit /b 1
)

echo.
echo Portable app folder:
echo dist\LiDARLabelTool
pause
