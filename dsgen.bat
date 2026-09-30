@echo off
rem dsgen GUI launcher. Double-click to open it.
rem If the environment (.venv) does not exist, it is created first with setup.ps1.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo First run: installing the environment, this may take a few minutes...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
    if errorlevel 1 (
        echo.
        echo Installation failed. Check the messages above.
        pause
        exit /b 1
    )
)

rem pythonw opens the GUI without leaving a console window open.
start "" ".venv\Scripts\pythonw.exe" -m dsgen
