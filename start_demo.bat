@echo off
title TTCS Demo - Truy xuat nguon goc nong san

echo Starting Backend...

start "Backend FastAPI" cmd /k "cd /d %~dp0backend && .venv\Scripts\activate && uvicorn app.main:app --reload"

timeout /t 5 > nul

echo Starting Frontend...

start "Frontend" cmd /k "cd /d %~dp0frontend && python -m http.server 5500"

timeout /t 3 > nul

echo Opening browser...

start http://127.0.0.1:5500

exit