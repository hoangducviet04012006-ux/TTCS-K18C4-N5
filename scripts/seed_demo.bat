@echo off
setlocal
cd /d "%~dp0..\backend"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m app.seeds.seed_demo
) else (
    python -m app.seeds.seed_demo
)
exit /b %errorlevel%
