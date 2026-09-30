@echo off
title TTCS Demo

start "Backend FastAPI" cmd /k "cd /d %~dp0backend && .venv\Scripts\activate && uvicorn app.main:app --reload"

timeout /t 3 > nul

start "Frontend" cmd /k "cd /d %~dp0frontend && python -m http.server 5500"

timeout /t 5 > nul

start chrome http://127.0.0.1:5500

pause