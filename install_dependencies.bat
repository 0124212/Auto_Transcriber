@echo off
echo ============================================================
echo Installing dependencies for Mojidori
echo ============================================================
echo.
echo This will install the required Python packages.
echo FFmpeg must also be installed and available on your PATH.
echo.

echo [STEP 1/2] Installing Python packages...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo [STEP 2/2] Checking FFmpeg installation...
ffmpeg -version >nul 2>&1
if %errorlevel% == 0 (
    echo FFmpeg is already installed and working!
    echo.
) else (
    echo FFmpeg not found. This is required for audio processing.
    echo Install FFmpeg from https://ffmpeg.org/download.html
    echo Then reopen this terminal and run: ffmpeg -version
)

echo.
echo ============================================================
echo Installation complete!
echo ============================================================
echo.
echo Next steps:
echo 1. Drop lecture files into the 'queue' folder
echo 2. Run START.bat or python transcribe_gui.py
echo 3. Check the 'processed' folder for transcripts
echo.
echo For more information, see README.md
echo.
pause
