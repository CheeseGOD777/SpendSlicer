@echo off
cd /d "%~dp0"
echo ============================================
echo   aws-cost-ultra
echo ============================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH.
    pause
    exit /b 1
)

if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment...
    python -m venv venv
)
call venv\Scripts\activate.bat

echo Installing dependencies...
pip install --quiet --upgrade pip
pip install --quiet -e ".[web,cur]"

echo.
echo Starting dashboard at http://127.0.0.1:8080/app
echo Press Ctrl+C to stop.
echo.
python -m aws_cost_ultra.web.app
