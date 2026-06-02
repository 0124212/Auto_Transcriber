# Auto Transcriber

A portable lecture transcription tool built on OpenAI Whisper. It watches a `queue/` folder, transcribes audio or video files, and writes clean transcript outputs to `processed/`.

This repository intentionally does not include lecture recordings, generated transcripts, archives, or model/cache files.

## Quick Start

### Windows

Double-click `START.bat`.

The Windows launcher uses a Conda environment named `transcriber`. If the environment does not exist yet, the launcher will create it and install the required Python packages.

### macOS

Double-click `START.command`.

On first run, macOS may require right-clicking the file, selecting **Open**, and confirming the security prompt.

### Workflow

1. Install Anaconda or Miniconda on Windows, or Python 3.8+ on macOS/Linux.
2. Install FFmpeg.
3. Drop audio/video files into `queue/`.
4. Start the GUI.
5. Choose a preset or adjust settings.
6. Click **GO**.

The first run can take a few minutes because Python packages may be installed automatically.

## Features

- **Auto-installation**: Python packages can be installed automatically on first run.
- **Simple GUI**: Presets and checkboxes for common transcription settings.
- **Automated Workflow**: Drop files in a folder and process them automatically
- **High-quality transcription**: Uses OpenAI Whisper models, including `large-v3`.
- **AI-ready formatting**: Adds readable paragraph breaks and optional timestamps.
- **Batch processing**: Process multiple recordings in one run.
- **Organized output**: Keeps outputs in per-recording folders under `processed/`.
- **Multiple model sizes**: Choose from `tiny` through `large-v3`.
- **Language options**: Auto-detect the language or specify it manually.

## Installation

### Step 1: Install Python or Conda

- Windows launcher path: install Anaconda or Miniconda so the `conda` command is available.
- Manual path: install Python 3.8 or higher from https://www.python.org/downloads/

### Step 2: Install FFmpeg (Required)
FFmpeg is needed for audio/video processing:

- **Windows**: 
  - Download from https://ffmpeg.org/download.html (or use https://www.gyan.dev/ffmpeg/builds/)
  - Extract and add the `bin` folder to your system PATH
  - Verify installation: `ffmpeg -version`
- **macOS**: `brew install ffmpeg`
- **Linux**: `sudo apt install ffmpeg` or `sudo yum install ffmpeg`

### Step 3: Install Python Dependencies

**Conda environment used by `START.bat` on Windows**

```bash
conda create -n transcriber python=3.11 -y
conda run -n transcriber python -m pip install -r requirements.txt
```

**CPU installation without Conda**

```bash
pip install -r requirements.txt
```

**GPU installation**

For NVIDIA GPU acceleration, install PyTorch with CUDA support from the official PyTorch instructions, then install this project's remaining dependencies:

```bash
pip install openai-whisper numpy ffmpeg-python pydub
```

Example CUDA installs:

```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
```

The script automatically uses CUDA when available and falls back to CPU otherwise.

### Step 4: Verify Installation

Test that everything is set up correctly:
```bash
python transcribe_lecture.py --help
```

If you have an NVIDIA GPU, verify CUDA is available:
```bash
python -c "import torch; print('CUDA Available:', torch.cuda.is_available())"
```

## Usage

### GUI Mode

- **Windows**: Double-click `START.bat`
- **Mac**: Double-click `START.command` (first time: right-click → Open)

The GUI launches the same transcription workflow with friendlier controls.

**Steps:**
1. **Double-click the launcher** - The GUI will open automatically

2. **Select Preset** (or customize):
   - **Fast (Lower Quality)**: Quick processing with small model
   - **Balanced (Recommended)**: Best quality/speed balance
   - **Best Quality (Slow)**: Highest accuracy

3. **Adjust Settings** (optional):
   - Model size dropdown
   - Checkboxes for audio normalization, timestamps, smart formatting

4. Click **GO**.

### Command Line Mode

1. **First Run**: The script automatically creates two folders:
   - `queue` - Drop your lecture files here
   - `processed` - Contains transcripts and enhanced audio for each lecture
   - `archived recordings.zip` - Contains original files organized by class code

2. **Drop Files**: Copy your lecture audio/video files into the `queue` folder

3. **Run Script**: Simply run:
   ```bash
   python transcribe_lecture.py
   ```

4. **Automatic Processing**: The script will:
   - Process all files in order
   - Generate formatted transcripts
   - Archive original files to zip (organized by class code)
   - Save processed files (transcripts, enhanced audio) to `processed/` folder

### Advanced Usage

```bash
# Use a smaller/faster model (lower quality)
python transcribe_lecture.py -m medium

# Specify language (faster if known)
python transcribe_lecture.py -l en

# Remove timestamps
python transcribe_lecture.py --no-timestamps

# Use simple paragraph formatting
python transcribe_lecture.py --no-segments

# Force CPU usage
python transcribe_lecture.py --device cpu

# Use a different base directory
python transcribe_lecture.py --base-path "C:/MyLectures"
```

### Model Sizes

- `tiny`: Fastest, lowest quality (~39M parameters)
- `base`: Fast, lower quality (~74M parameters)
- `small`: Balanced (~244M parameters)
- `medium`: Good quality (~769M parameters)
- `large-v2`: High quality (~1550M parameters)
- `large-v3`: **Best quality** (~1550M parameters, recommended)

**Note**: Larger models provide better accuracy but are slower. For lectures, `large-v3` is recommended for best results.

## Output Format

The script generates two files:

1. **`*_transcript.txt`**: Well-formatted text file optimized for AI reading
   - Includes header with metadata
   - Paragraph breaks for readability
   - Optional timestamps
   - Clean formatting

2. **`*_raw.json`**: Raw transcription data with full details
   - Complete segment information
   - Word-level timestamps
   - Confidence scores
   - Useful for advanced processing

## Supported Formats

Whisper supports most audio and video formats including:
- MP3, MP4, WAV, M4A, FLAC, OGG, WEBM, and more
- Any format that FFmpeg can decode

## Tips for Best Results

1. **Use `large-v3` model** for highest quality transcriptions
2. **Specify language** if known (faster processing)
3. **Good audio quality** = better transcription
4. **Long lectures** may take time - be patient!
5. The output is already formatted for AI summarization tools

## Example Workflow

1. Drop `lecture1.mp4`, `lecture2.mp3`, and `lecture3.wav` into `queue`

2. Run:
   ```bash
   python transcribe_lecture.py -m large-v3 -l en
   ```

3. Results:
   - `processed/` contains:
     - `lecture1_transcript.txt` - Formatted for AI
     - `lecture1_transcript_raw.json` - Raw data
     - `lecture1_enhanced.wav` - Enhanced audio (if audio normalization enabled)
     - `lecture2_transcript.txt`
     - `lecture2_transcript_raw.json`
     - `lecture2_enhanced.wav`
     - `lecture3_transcript.txt`
     - `lecture3_transcript_raw.json`
     - `lecture3_enhanced.wav`

## Repository Hygiene

The following paths are ignored by Git:

- `queue/` contents
- `processed/` contents
- audio/video files
- zip archives
- Python caches and virtual environments
- local environment and secret files

Keep real recordings and generated transcripts out of the repository.

## Troubleshooting

- **"ffmpeg not found"**: Install FFmpeg and ensure it's in your PATH
- **Slow transcription**: Use a smaller model or ensure GPU is available
- **Memory errors**: Use a smaller model or process shorter segments
- **Poor quality**: Ensure good audio quality, use larger model, or specify language
