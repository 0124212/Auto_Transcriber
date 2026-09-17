# Auto Transcriber

Whisper-powered lecture transcription with a modern web UI. Works on **Windows, macOS, and Linux**.

Drop audio/video files → get clean, AI-ready transcripts.

## Quick Start

```bash
# 1. Clone or download
git clone https://github.com/0124212/Auto_Transcriber.git
cd Auto_Transcriber

# 2. Launch (auto-installs everything)
python start.py
```

Opens at **http://localhost:8080**. That's it.

### Prerequisites

- **Python 3.9+** — [python.org](https://www.python.org/downloads/)
- **FFmpeg** — [ffmpeg.org](https://ffmpeg.org/download.html)
  - macOS: `brew install ffmpeg`
  - Linux: `sudo apt install ffmpeg` or `sudo dnf install ffmpeg`
  - Windows: `winget install ffmpeg`

Everything else is installed automatically on first run.

## Usage

### Web UI (recommended)

```bash
python start.py              # Default port 8080
python start.py --port 9000  # Custom port
python start.py --no-browser # Don't auto-open browser
```

1. **Drop files** onto the web page (or click to browse)
2. **Pick a preset** (Fast / Balanced / Best Quality)
3. **Click Start** — watch real-time progress
4. **View transcripts** in the results panel

### CLI (legacy)

```bash
python start.py --cli
# or directly:
python transcribe_lecture.py -m large-v3 -l en
```

## Features

- **Cross-platform** — identical experience on Windows, macOS, Linux
- **Modern web UI** — drag & drop, presets, real-time progress
- **Auto-install** — Python packages installed on first run
- **AI-ready output** — clean paragraphs, optional timestamps
- **Audio normalization** — auto-enhances quiet recordings
- **Batch processing** — process multiple files at once
- **Multiple models** — tiny through large-v3
- **10 languages** — auto-detect or specify manually
- **Raw JSON output** — full segment data with confidence scores

## Model Sizes

| Model | Speed | Quality | Use Case |
|-------|-------|---------|----------|
| `tiny` | Fastest | Low | Quick drafts |
| `base` | Fast | Low-Med | |
| `small` | Medium | Medium | Fast preset |
| `medium` | Slow | Good | |
| `large-v3` | Slowest | Best | Recommended |

## Project Structure

```
Auto_Transcriber/
├── start.py              # Universal launcher
├── app.py                # Flask web UI server
├── core.py               # Transcription engine (importable)
├── transcribe_lecture.py # CLI mode (legacy)
├── transcribe_gui.py     # tkinter GUI (legacy)
├── templates/
│   └── index.html        # Web UI
├── queue/                # Drop files here
├── processed/            # Output transcripts
├── prompt_*.md           # AI prompt templates for post-processing
└── requirements.txt
```

## Output

Each lecture gets a folder under `processed/`:

```
processed/
└── C188 Lecture 1/
    ├── C188 Lecture 1_transcript.txt      # Formatted transcript
    ├── C188 Lecture 1_transcript_raw.json # Full Whisper output
    └── C188 Lecture 1_enhanced.wav        # Normalized audio (if enabled)
```

## Post-Processing with AI

The `prompt_*.md` files are templates for turning transcripts into study materials:

- **prompt_descriptive_summary.md** — Full detailed notes (open-book exams)
- **prompt_condensed_notes.md** — High-yield study notes
- **prompt_cheat_sheet.md** — Ultra-dense one-page reference

Paste a transcript into your AI tool with one of these prompts for instant study materials.

## Supported Formats

MP3, MP4, WAV, M4A, FLAC, OGG, WebM, AVI, MOV, MKV, AAC, WMA, MPEG — anything FFmpeg can decode.

## License

MIT
