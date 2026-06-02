@echo off
REM Conda launcher for Auto Transcriber

cd /d "%~dp0"

REM Fix OpenMP duplicate library conflict (PyTorch + Intel MKL on Windows)
set KMP_DUPLICATE_LIB_OK=TRUE

set CONDA_ENV=transcriber

where conda >nul 2>&1
if errorlevel 1 (
    echo.
    echo ========================================
    echo ERROR: Conda not found!
    echo ========================================
    echo.
    echo Install Anaconda or Miniconda, then reopen this terminal.
    echo.
    pause
    exit /b 1
)

conda run -n %CONDA_ENV% python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ========================================
    echo Creating Conda Environment
    echo ========================================
    echo.
    echo Creating environment: %CONDA_ENV%
    conda create -n %CONDA_ENV% python=3.11 -y
    if errorlevel 1 (
        echo ERROR: Failed to create Conda environment.
        pause
        exit /b 1
    )
)

REM Check if required packages are installed
conda run -n %CONDA_ENV% python -c "import whisper, torch, numpy, ffmpeg, pydub; from pydub import AudioSegment" >nul 2>&1
if errorlevel 1 (
    echo.
    echo ========================================
    echo Installing Required Packages
    echo ========================================
    echo.
    echo Installing packages into Conda environment: %CONDA_ENV%
    echo This may take a few minutes. Please wait...
    echo.

    conda run -n %CONDA_ENV% python -m pip install --upgrade pip
    conda run -n %CONDA_ENV% python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed to install packages!
        pause
        exit /b 1
    )

    echo.
    echo ========================================
    echo Packages Installed Successfully!
    echo ========================================
    echo.
    timeout /t 2 >nul
) else (
    echo All required packages are installed.
)

REM Launch the GUI using the Conda environment
echo.
echo Starting Auto Transcriber...
conda run -n %CONDA_ENV% python transcribe_gui.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo ERROR: Failed to start the GUI
    echo ========================================
    echo.
    echo Check that all dependencies are installed.
    echo.
    pause
    exit /b 1
)
