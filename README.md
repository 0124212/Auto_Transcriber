# Auto Transcriber

Whisper-powered lecture transcription with a modern web UI. Works on **Windows, macOS, and Linux**.

Drop audio/video files → get clean, AI-ready transcripts.

## Install

### Windows — the easy way (no Python, no setup)

1. Go to **Releases** (right side of the GitHub page) and download `AutoTranscriber-win64.zip`
2. Unzip it anywhere
3. Double-click **`AutoTranscriber.exe`**
4. Your browser opens with the app. Done.

First transcription downloads the speech model once (~3 GB, automatic) — after that it's instant.
Tip: paste a free [Groq key](https://console.groq.com/keys) in Engine settings to skip the download entirely and transcribe ~10× faster in the cloud.

### Windows — from source (double-click)

Double-click **`START.bat`**. It installs Python/FFmpeg itself if they're missing, then opens the app.

### macOS / Linux — one command

```bash
git clone https://github.com/0124212/Auto_Transcriber.git
cd Auto_Transcriber
python3 start.py
```

Opens at **http://localhost:8080**. Python packages auto-install on first run; you only need FFmpeg (`brew install ffmpeg` / `sudo apt install ffmpeg`).

## Usage

### Web UI (recommended)

```bash
python start.py              # Default port 8080
python start.py --port 9000  # Custom port
python start.py --no-browser # Don't auto-open browser
```

1. **Drop files** onto the web page (or click to browse)
2. **Pick a preset** (Fast / Balanced / Best Quality)
3. **Click Start** — watch real-time progress in the live console
4. **Copy** any transcript with one click — optionally bundled with a study prompt, ready to paste into your AI

Quality-of-life extras:
- **👀 Watch mode** — tick the box in Queue and the app auto-starts whenever new files land. Drop & forget.
- **📦 Auto-archive** — finished originals move to `archive/<ClassCode>/`, so the queue never double-processes.
- **📱 Done ping** — set `NTFY_TOPIC` in `.env` and your phone buzzes when a long job finishes.
- **💾 Settings memory** — provider, model, sliders, and toggles persist across restarts.

### CLI (legacy)

```bash
python start.py --cli
# or directly:
python transcribe_lecture.py -m large-v3 -l en
```

## Features

- **Free, always** — local engines cost $0 forever; Groq cloud tier is free too. Only OpenAI bills.
- **Two local engines** — classic Whisper or faster-whisper (~4× quicker, same accuracy)
- **Clean transcripts** — artifact cleanup, verify-flags on shaky segments, word counts, reading time
- **Organized outputs** — `.txt` transcript + `.srt`/`.vtt` subtitles + raw JSON, per lecture
- **Modern web UI** — drag & drop, presets, live terminal console
- **Watch mode** — auto-starts when new files land in `queue/`
- **Audio pipeline** — high-pass, mono, 16 kHz, 2-pass gain, limiter, verified by re-measure
- **Batch processing** — whole queue in one run, originals auto-archived by class code
- **10 languages** — auto-detect or specify manually

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
