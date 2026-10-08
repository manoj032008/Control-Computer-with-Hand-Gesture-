@echo off
cd /d "%~dp0"
echo ============================================================
echo  Hand Gesture Control — Desktop Companion
echo ============================================================
echo.
echo Installing required packages...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Failed to install required packages.
    pause
    exit /b %errorlevel%
)
echo.
echo Starting companion server on ws://127.0.0.1:8765 ...
echo Open your deployed website and click "Try Live Demo".
echo Press Ctrl+C to stop.
echo.
python gesture_companion.py
pause
