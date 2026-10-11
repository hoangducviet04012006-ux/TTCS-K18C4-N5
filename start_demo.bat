@echo off
setlocal
title AgriTrace Sprint 1-3 Demo
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_demo.ps1" %*
if errorlevel 1 (
    echo [LOI] Khong khoi dong duoc demo. Xem thong bao va log o tren.
    pause
    exit /b 1
)
exit /b 0
