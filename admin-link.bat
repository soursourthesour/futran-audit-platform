@echo off
REM Futran Audit Platform - get a link to set (or reset) an administrator's password.
setlocal
cd /d "%~dp0"
set "VENV=%LOCALAPPDATA%\FutranAuditPlatform\venv"
if not exist "%VENV%\Scripts\activate.bat" (echo Run setup.bat first. & pause & exit /b 1)
call "%VENV%\Scripts\activate.bat"
cd backend
copy /y ..\.env .env >nul
set "ADMIN_EMAIL="
set "ADMIN_NAME="
set /p "ADMIN_EMAIL=Administrator work email: "
if "%ADMIN_EMAIL%"=="" (echo No email entered. & pause & exit /b 1)
set /p "ADMIN_NAME=Full name (only needed for a new account, press Enter to skip): "
if "%ADMIN_NAME%"=="" (python -m app.cli admin-link --email "%ADMIN_EMAIL%") else (python -m app.cli admin-link --email "%ADMIN_EMAIL%" --name "%ADMIN_NAME%")
echo.
echo Keep run.bat open, then open the link above in your browser.
pause
