@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Facebook Traffic Master Pro

if exist "FacebookTrafficMaster.exe" (
    "FacebookTrafficMaster.exe"
) else (
    python launcher.py
)
if errorlevel 1 (
    echo.
    echo [!] Gap loi khi khoi chay. Nhan Enter de thoat...
    pause >nul
)
