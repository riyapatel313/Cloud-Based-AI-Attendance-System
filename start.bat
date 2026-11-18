@echo off
cd /d "%~dp0"
if not exist venv\Scripts\activate.bat (
  echo Creating virtual environment...
  python -m venv venv || (echo Python 3.9+ is required. Install it from python.org and tick "Add to PATH". & pause & exit /b 1)
)
call venv\Scripts\activate.bat
echo Installing packages (first time takes a few minutes)...
pip install -r requirements.txt || (pause & exit /b 1)
python run.py
pause
