@echo off
REM =====================================================================
REM  Mojidori — double-click to run. Opens the web UI in your browser.
REM  First run installs what's missing automatically. Just wait.
REM =====================================================================
cd /d "%~dp0"
set KMP_DUPLICATE_LIB_OK=TRUE

REM --- find Python (py launcher first, it's the Windows standard) ---
where py >nul 2>&1
if %errorlevel%==0 ( set "PY=py -3" & goto :have_python )
where python >nul 2>&1
if %errorlevel%==0 ( set "PY=python" & goto :have_python )

echo.
echo  Python not found. Attempting automatic install via winget...
echo.
winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo.
    echo  Automatic install failed. Please install Python manually:
    echo    https://www.python.org/downloads/
    echo  (tick "Add python.exe to PATH" during setup)
    echo.
    pause
    exit /b 1
)
echo.
echo  Python installed. Please DOUBLE-CLICK this file again to start.
echo.
pause
exit /b 0

:have_python
REM --- ffmpeg check (start.py also checks, this preinstalls it silently) ---
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo  FFmpeg not found. Installing via winget (one-time)...
    winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements
)

echo.
echo  Starting Mojidori...
echo.
%PY% start.py %*

if errorlevel 1 (
    echo.
    echo  Something went wrong — the error is above.
    echo.
    pause
)
