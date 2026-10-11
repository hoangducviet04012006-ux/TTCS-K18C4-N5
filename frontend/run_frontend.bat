@echo off
chcp 65001 > nul
title Frontend Web Server (Port 5500)

cd /d "%~dp0.."

echo ======================================================================
echo    Frontend Web Server - http://127.0.0.1:5500
echo ======================================================================
echo.

if exist "backend\.venv\Scripts\python.exe" (
    "backend\.venv\Scripts\python.exe" -m http.server 5500 --directory frontend
) else (
    python -m http.server 5500 --directory frontend
)

if %errorlevel% neq 0 (
    echo.
    echo [LOI] Frontend HTTP Server bi loi hoac gap su co!
    pause
)
