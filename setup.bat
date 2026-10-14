@echo off
REM Futran Audit Platform - one-time setup on Windows. Run from this folder.
REM Python packages and the database live in %LOCALAPPDATA%\FutranAuditPlatform, outside OneDrive.
setlocal
cd /d "%~dp0"
set "HOMEDIR=%LOCALAPPDATA%\FutranAuditPlatform"
set "VENV=%HOMEDIR%\venv"
where python >nul 2>nul || (echo Python 3.11 or later is required. Install it from python.org and tick "Add python.exe to PATH". & pause & exit /b 1)
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)" || (echo Python 3.11 or later is required. & pause & exit /b 1)
if not exist "backend\app\static\index.html" (echo The web app files are missing from backend\app\static. Copy the project again. & pause & exit /b 1)
if not exist "%HOMEDIR%" mkdir "%HOMEDIR%"
if not exist "%VENV%\Scripts\python.exe" (python -m venv "%VENV%" || (echo Could not create the Python environment. & pause & exit /b 1))
call "%VENV%\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
pip install -e backend || (echo Installing packages failed. Check your internet connection and try again. & pause & exit /b 1)
python backend\scripts\configure_env.py || (echo Could not write the .env settings file. & pause & exit /b 1)
cd backend
copy /y ..\.env .env >nul
alembic upgrade head || (echo Database setup failed. & pause & exit /b 1)
python -m app.cli seed-reference
echo.
echo Create the first administrator account (press Enter to skip if you already have one).
set "ADMIN_EMAIL="
set /p "ADMIN_EMAIL=Administrator work email: "
if not "%ADMIN_EMAIL%"=="" (
  set /p "ADMIN_NAME=Administrator full name: "
  call python -m app.cli create-admin --email "%%ADMIN_EMAIL%%" --name "%%ADMIN_NAME%%"
)
echo.
echo Setup complete. Start the platform with run.bat, then open the link above to set your password.
pause
