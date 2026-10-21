@echo off
setlocal
cd /d "%~dp0"
title AgriTrace - He thong truy xuat nguon goc nong san
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_app.ps1" %*
