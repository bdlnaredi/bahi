@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0TallySync.ps1" -Force
echo.
pause
