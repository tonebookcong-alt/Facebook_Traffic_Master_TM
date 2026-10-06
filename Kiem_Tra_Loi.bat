@echo off
chcp 65001 >nul
title KIEM TRA VA CHAN DOAN LOI HE THONG

echo ======================================================================
echo   DANG KHOI DONG TRINH CHAN DOAN LOI FACEBOOK TRAFFIC MASTER...
echo ======================================================================

set PY_BIN=
if exist "%~dp0python_runtime\python.exe" (
    set "PY_BIN=%~dp0python_runtime\python.exe"
) else (
    set "PY_BIN=python"
)

"%PY_BIN%" "%~dp0Kiem_Tra_Loi.py"

echo.
echo ======================================================================
echo   DA KIEM TRA XONG! DANG MO FILE KET QUA KET_QUA_KIEM_TRA.txt...
echo ======================================================================

if exist "%~dp0KET_QUA_KIEM_TRA.txt" (
    start notepad "%~dp0KET_QUA_KIEM_TRA.txt"
)

pause
