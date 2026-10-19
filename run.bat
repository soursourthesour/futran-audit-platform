@echo off
REM Futran Audit Platform - start on this computer, then open http://localhost:8000
setlocal
cd /d "%~dp0"
set "VENV=%LOCALAPPDATA%\FutranAuditPlatform\venv"
if not exist "%VENV%\Scripts\activate.bat" (echo Run setup.bat first. & pause & exit /b 1)
call "%VENV%\Scripts\activate.bat"
cd backend
copy /y ..\.env .env >nul
alembic upgrade head || (echo Database update failed. & pause & exit /b 1)
if "%1"=="--reset-demo" (python -m app.cli reset-demo || (echo The demo was not loaded. & pause & exit /b 1))
start "" http://localhost:8000
uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8000
