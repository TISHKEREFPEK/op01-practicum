@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0runtime\python.exe" (
    set "OP01_POSTGRES_DSN="
    "%~dp0runtime\python.exe" -B server.py --open-browser
) else (
    python -B server.py --open-browser
)
if errorlevel 1 pause
