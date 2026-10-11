@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    set "DEMO_PYTHON=%~dp0.venv\Scripts\python.exe"
) else if exist "venv\Scripts\python.exe" (
    set "DEMO_PYTHON=%~dp0venv\Scripts\python.exe"
) else (
    set "DEMO_PYTHON=python"
)
"%DEMO_PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
if errorlevel 1 (
    echo [LOI] Backend khong khoi dong duoc. Kiem tra thong bao o tren.
    pause
    exit /b 1
)
