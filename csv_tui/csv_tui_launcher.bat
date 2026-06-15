@echo off
setlocal

title CSV Analyzer

set "SCRIPT=%~dp0csv_tui.py"

where python >nul 2>&1
if errorlevel 1 (
    echo Python not found in PATH.
    echo Install Python from https://python.org and ensure it is added to PATH.
    pause
    exit /b 1
)

if "%~1"=="" (
    python "%SCRIPT%"
) else (
    python "%SCRIPT%" "%~1"
)

if errorlevel 1 (
    echo.
    echo CSV Analyzer exited with an error. Press any key to close.
    pause >nul
)

endlocal
