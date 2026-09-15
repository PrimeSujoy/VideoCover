REM # Don't Remove Credit Tg - @NexonBots
REM # Subscribe YouTube Channel For Amazing Bot https://youtube.com/@NexonBots
REM # Ask Doubt on telegram @NexonContactBot

@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  py -3.12 -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python bot.py

pause
