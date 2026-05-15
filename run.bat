@echo off
REM Launches the Peregryn app on Windows.

cd /d "%~dp0"

if not exist ".venv" (
  echo Creating virtual environment...
  python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Installing dependencies...
pip install --upgrade pip >nul
pip install -r requirements.txt

if not exist ".env" (
  echo Creating .env from .env.example - edit it to add your GEMINI_API_KEY and CLERK keys.
  copy .env.example .env
)

echo.
echo ============================================================
echo   Peregryn is starting on http://localhost:8000
echo ============================================================
echo.

uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
