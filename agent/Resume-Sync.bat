@echo off
schtasks /Change /TN "Tally Mobile Sync" /ENABLE >nul 2>&1
if errorlevel 1 (echo Could not find the Bahi sync task. Run Setup.bat first.) else (echo Automatic sync to Bahi is running again, every 10 minutes.)
echo.
pause
