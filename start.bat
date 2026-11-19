@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Install Python 3.10 or newer from python.org and tick "Add Python to PATH".
  pause
  exit /b 1
)
if not exist venv\Scripts\activate.bat python -m venv venv
call venv\Scripts\activate.bat
python -m pip install -q -r requirements.txt
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:5000"
python app.py
pause
