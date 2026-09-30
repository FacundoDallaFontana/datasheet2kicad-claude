@echo off
rem Lanzador de la GUI de dsgen. Doble clic para abrirla.
rem Si el entorno (.venv) no existe, lo crea primero con setup.ps1.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo Primera ejecucion: instalando el entorno, puede tardar unos minutos...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
    if errorlevel 1 (
        echo.
        echo Fallo la instalacion. Revisa los mensajes de arriba.
        pause
        exit /b 1
    )
)

rem pythonw abre la GUI sin dejar una ventana de consola abierta.
start "" ".venv\Scripts\pythonw.exe" -m dsgen
