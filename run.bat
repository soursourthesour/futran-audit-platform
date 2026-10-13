@echo off
REM Futran Audit Platform - start on this computer. Use "run.bat --reset-demo" to rebuild the demo data.
setlocal
cd /d "%~dp0"
if not exist .venv (echo Run setup.bat first. & pause & exit /b 1)
call .venv\Scripts\activate.bat
cd backend
copy /y ..\.env .env >nul
alembic upgrade head || (echo Database update failed. & pause & exit /b 1)
if "%1"=="--reset-demo" python -m app.cli reset-demo
start "" http://localhost:8000
uvicorn --factory app.main:create_app --host 127.0.0.1 --port 8000
