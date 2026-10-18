@echo off
setlocal
cd /d "%~dp0"

echo === Vremya ryadom ===
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.10+ and add it to PATH.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Failed to create .venv
    pause
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"

echo Installing dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] Failed to install dependencies
  pause
  exit /b 1
)

echo.
echo Server: http://127.0.0.1:5000
echo Press Ctrl+C to stop.
echo.
python main.py

endlocal
