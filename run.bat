@echo off
REM Run CostSight from a source checkout: create a venv, install, serve.
REM Prefer the desktop build or `pip install costsight[web,cur]` for normal use.
cd /d "%~dp0"
echo ============================================
echo   CostSight
echo ============================================
echo.

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH.
    pause
    exit /b 1
)

python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if %errorlevel% neq 0 (
    echo ERROR: Python 3.10 or newer is required.
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
REM Set COSTSIGHT_RELOAD=1 to enable uvicorn autoreload while hacking.
python -m costsight.web.app
