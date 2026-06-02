#!/bin/bash
# Simple launcher for Auto Transcriber
# Double-click this file on Mac to start the transcription system

# Change to the script's directory
cd "$(dirname "$0")"

echo ""
echo "========================================"
echo "Auto Transcriber"
echo "========================================"
echo ""

# Check if Python 3 is available
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo ""
    echo "========================================"
    echo "ERROR: Python not found!"
    echo "========================================"
    echo ""
    echo "Python is not installed or not in your PATH."
    echo ""
    echo "Please install Python:"
    echo "  - Mac: brew install python3"
    echo "  - Or download from https://www.python.org/downloads/"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi

echo "Using Python: $PYTHON_CMD"
$PYTHON_CMD --version
echo ""

# Check if required packages are installed
echo "Checking for required packages..."
$PYTHON_CMD -c "import whisper; import torch; import numpy; import pydub" 2>/dev/null

if [ $? -ne 0 ]; then
    echo ""
    echo "========================================"
    echo "Installing Required Packages"
    echo "========================================"
    echo ""
    echo "This is your first run! Installing required packages..."
    echo "This may take a few minutes. Please wait..."
    echo ""
    
    # Install requirements
    if [ -f "requirements.txt" ]; then
        echo "Installing from requirements.txt..."
        $PYTHON_CMD -m pip install --upgrade pip
        $PYTHON_CMD -m pip install -r requirements.txt
        
        if [ $? -ne 0 ]; then
            echo ""
            echo "ERROR: Failed to install packages!"
            echo ""
            echo "Please try manually:"
            echo "  pip install -r requirements.txt"
            echo ""
            read -p "Press Enter to exit..."
            exit 1
        fi
        
        echo ""
        echo "========================================"
        echo "Packages Installed Successfully!"
        echo "========================================"
        echo ""
        sleep 2
    else
        echo "ERROR: requirements.txt not found!"
        echo ""
        read -p "Press Enter to exit..."
        exit 1
    fi
else
    echo "All required packages are installed."
fi

# Launch the GUI
echo ""
echo "Starting Auto Transcriber..."
$PYTHON_CMD transcribe_gui.py

if [ $? -ne 0 ]; then
    echo ""
    echo "========================================"
    echo "ERROR: Failed to start the GUI"
    echo "========================================"
    echo ""
    echo "The GUI failed to launch. Possible issues:"
    echo "- Missing dependencies (try running: pip install -r requirements.txt)"
    echo "- Python version too old (need Python 3.8+)"
    echo ""
    read -p "Press Enter to exit..."
    exit 1
fi
