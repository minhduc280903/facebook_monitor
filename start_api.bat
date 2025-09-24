@echo off
echo Starting Facebook Post Monitor API Server...

:: Set UTF-8 encoding
chcp 65001 >nul

:: Use system Python
set PYTHON_EXE=C:\Python313\python.exe

if not exist "%PYTHON_EXE%" (
    echo ERROR: System Python not found at %PYTHON_EXE%
    pause
    exit /b 1
)

echo Starting API server on http://localhost:8000
%PYTHON_EXE% api/main.py

pause






