@echo off
schtasks /Change /TN "Tally Mobile Sync" /DISABLE >nul 2>&1
if errorlevel 1 (echo Could not find the Bahi sync task. Run Setup.bat first.) else (echo Automatic sync to Bahi is paused on this PC. Run Resume-Sync.bat to start it again.)
echo.
pause
