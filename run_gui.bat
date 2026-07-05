@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Project Python environment was not found.
    echo Run the setup steps in docs\USER_MANUAL.md first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m lidar_label_tool gui
if errorlevel 1 (
    echo.
    echo The application ended with an error. See docs\USER_MANUAL.md.
    pause
)
