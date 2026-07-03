@echo off
cd /d "%~dp0"

echo [Conduit] Starting backend...

REM Try venv first
if exist ".venv\Scripts\uvicorn.exe" (
    .venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
    goto :eof
)

REM Try py launcher (most reliable on Windows)
py -m uvicorn app.main:app --reload --port 8000 2>nul
if %errorlevel% equ 0 goto :eof

REM Try python
python -m uvicorn app.main:app --reload --port 8000 2>nul
if %errorlevel% equ 0 goto :eof

REM Try python3
python3 -m uvicorn app.main:app --reload --port 8000 2>nul
if %errorlevel% equ 0 goto :eof

echo.
echo [ERROR] Could not find Python. Make sure Python is installed.
echo Run: pip install -r requirements.txt
pause
