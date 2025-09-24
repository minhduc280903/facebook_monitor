@echo off
echo Starting Facebook Post Monitor System...
echo Using system Python interpreter...

:: Set UTF-8 encoding
chcp 65001 >nul

:: Use system Python instead of UV environment
set PYTHON_EXE=C:\Python313\python.exe

:: Check if system Python exists
if not exist "%PYTHON_EXE%" (
    echo ERROR: System Python not found at %PYTHON_EXE%
    echo Please install Python 3.13 or modify the path in this script
    pause
    exit /b 1
)

:: Install required packages if needed
echo Installing required packages...
%PYTHON_EXE% -m pip install playwright redis psycopg2-binary fastapi uvicorn pydantic pydantic-settings

:: Install playwright browsers
echo Installing Playwright browsers...
%PYTHON_EXE% -m playwright install chromium

:: Start the system
echo Starting multi-queue system...
%PYTHON_EXE% run_multi_queue_system.py --full

pause






