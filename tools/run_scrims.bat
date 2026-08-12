@echo off
REM Overnight scrims vs the top 5 ladder teams, one batch every 20 minutes.
REM Whatever submission is ACTIVE is what gets tested. Ctrl-C to stop.
cd /d "%~dp0"
python scrimbot.py --top 5 --every 20
pause
