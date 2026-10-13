@echo off
REM Futran Audit Platform - one-time setup on Windows. Run from this folder.
setlocal
cd /d "%~dp0"
where python >nul 2>nul || (echo Python 3.11 or later is required. Install it from python.org and tick "Add python.exe to PATH". & pause & exit /b 1)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" || (echo Python 3.11 or later is required. & pause & exit /b 1)
if not exist .venv (python -m venv .venv || (echo Could not create the virtual environment. & pause & exit /b 1))
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -e backend || (echo Installing packages failed. Check your internet connection and try again. & pause & exit /b 1)
if not exist .env copy .env.example .env >nul
cd backend
if not exist data mkdir data
copy /y ..\.env .env >nul
alembic upgrade head || (echo Database setup failed. & pause & exit /b 1)
python -m app.cli seed-reference
echo.
echo Setup complete. Start the platform with run.bat (or "run.bat --reset-demo" to load the demo clients).
pause
