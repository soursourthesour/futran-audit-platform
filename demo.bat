@echo off
REM Futran Audit Platform - load the demo clients and start. This REPLACES the local database.
cd /d "%~dp0"
echo This deletes the local database and loads the demo clients.
choice /M "Continue"
if errorlevel 2 exit /b 0
call run.bat --reset-demo
