#!/usr/bin/env python3
"""
Auto Transcriber — Core transcription engine.
Importable module: used by both CLI (transcribe_lecture.py) and web UI (app.py).

Providers:
  - local : on-device openai-whisper (private, slower, no key needed)
  - groq  : Groq Cloud whisper-large-v3-turbo (FREE tier, very fast, needs key)
  - openai: OpenAI whisper-1 (paid, needs key)

Log protocol: progress_cb receives plain strings with standard prefixes so any
frontend can render a terminal-style console:
  [STEP n/m] step headers      [OK] success        [WARN] warning
  [ERR] error                  [AUDIO] audio stage [API] api stage
"""

import os
import sys
import json
import math
import re
import shutil
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, List, Callable, Dict, Any

os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Load .env (API keys) if python-dotenv is available — never fatal if missing.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

AUDIO_VIDEO_EXTENSIONS = {
    '.mp3', '.mp4', '.wav', '.m4a', '.flac', '.ogg', '.webm',
    '.avi', '.mov', '.mkv', '.wmv', '.aac', '.wma', '.mpeg', '.mpg'
}

PRESETS = {
    "fast": {
        "model": "small",
        "normalize_audio": True,
        "timestamps": False,
        "segments": True,
        "language": "en",
    },
    "balanced": {
        "model": "large-v3",
        "normalize_audio": True,
        "timestamps": True,
        "segments": True,
        "language": "en",
    },
    "best": {
        "model": "large-v3",
        "normalize_audio": True,
        "timestamps": True,
        "segments": True,
        "language": "en",
    },
}

LANGUAGES = {
    "Auto-detect": None,
    "English": "en",
    "Spanish": "es",
    "French": "fr",
    "German": "de",
    "Italian": "it",
    "Portuguese": "pt",
    "Chinese": "zh",
    "Japanese": "ja",
    "Korean": "ko",
}

MODEL_SIZES = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]

# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
PROVIDERS: Dict[str, Dict[str, Any]] = {
    "local": {
        "label": "Local Whisper (private, no key)",
        "needs_key": False,
        "models": MODEL_SIZES,
        "default_model": "large-v3",
    },
    "fast": {
        "label": "Local Fast — faster-whisper (free, ~4x quicker)",
        "needs_key": False,
        "models": ["tiny", "base", "small", "medium", "large-v3"],
        "default_model": "large-v3",
    },
    "groq": {
        "label": "Groq Cloud — FREE tier (fast)",
        "needs_key": True,
        "env_var": "GROQ_API_KEY",
        "key_url": "https://console.groq.com/keys",
        "models": ["whisper-large-v3-turbo", "whisper-large-v3"],
        "default_model": "whisper-large-v3-turbo",
        "max_mb": 25,
    },
    "openai": {
        "label": "OpenAI Whisper API (paid)",
        "needs_key": True,
        "env_var": "OPENAI_API_KEY",
        "key_url": "https://platform.openai.com/api-keys",
        "models": ["whisper-1"],
        "default_model": "whisper-1",
        "max_mb": 25,
    },
}

# Audio pipeline defaults
DEFAULT_TARGET_DBFS = -20.0
MAX_SAFE_GAIN_DB = 30.0
HIGHPASS_HZ = 80            # kills rumble / hum / DC offset
WHISPER_RATE = 16000        # Whisper's native sample rate
API_CHUNK_MIN = 10          # minutes per API chunk (stays well under 25 MB)
SILENCE_DBFS = -50.0        # below this ≈ digital silence


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def check_cuda() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except (ImportError, AttributeError, RuntimeError):
        return False


def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def extract_class_code(filename: str) -> str:
    match = re.match(r'^([A-Z]+[0-9]+)', filename.upper())
    return match.group(1) if match else "Unknown"


def get_audio_files(folder: Path) -> List[Path]:
    files = [f for f in folder.iterdir()
             if f.is_file() and f.suffix.lower() in AUDIO_VIDEO_EXTENSIONS]
    files.sort(key=lambda x: x.name.lower())
    return files


def cleanup_files(paths) -> int:
    """Best-effort delete of temp files. Returns count removed."""
    removed = 0
    for p in paths or []:
        try:
            p = Path(p)
            if p.is_file():
                p.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def resolve_api_key(provider: str, explicit: str = None) -> Optional[str]:
    """Explicit key > environment > None."""
    if explicit:
        return explicit.strip() or None
    env_var = PROVIDERS.get(provider, {}).get("env_var")
    if env_var:
        return os.environ.get(env_var) or None
    return None


# ---------------------------------------------------------------------------
# Audio analysis — deep inspection before touching a single sample
# ---------------------------------------------------------------------------

@dataclass
class AudioReport:
    duration_sec: float = 0.0
    channels: int = 0
    sample_rate: int = 0
    rms_dbfs: float = float("-inf")
    peak_dbfs: float = float("-inf")
    dynamic_range_db: float = 0.0
    silence_ratio: float = 0.0      # fraction of 1-sec windows below SILENCE_DBFS
    is_silent: bool = False
    is_quiet: bool = False
    is_very_quiet: bool = False
    is_loud: bool = False
    is_clipped: bool = False
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []

    def summary(self) -> str:
        return (f"{self.duration_sec/60:.1f} min · {self.channels}ch @ {self.sample_rate}Hz · "
                f"RMS {self.rms_dbfs:.1f} dBFS · peak {self.peak_dbfs:.1f} dBFS · "
                f"dyn-range {self.dynamic_range_db:.1f} dB · silence {self.silence_ratio*100:.0f}%")


def analyze_audio(path: Path) -> AudioReport:
    """Full diagnostic pass. Raises RuntimeError on unreadable/empty audio."""
    from pydub import AudioSegment

    try:
        audio = AudioSegment.from_file(str(path))
    except Exception as e:
        raise RuntimeError(f"Could not decode audio ({e}). Is FFmpeg installed?")

    rep = AudioReport()
    rep.duration_sec = len(audio) / 1000.0
    rep.channels = audio.channels
    rep.sample_rate = audio.frame_rate

    if rep.duration_sec < 1.0:
        raise RuntimeError(f"Audio is only {rep.duration_sec:.1f}s — too short to transcribe.")

    rep.rms_dbfs = audio.dBFS
    if rep.rms_dbfs == float("-inf"):
        raise RuntimeError("No audio signal detected (digital silence). Check the source file.")

    peak_ratio = audio.max / audio.max_possible_amplitude if audio.max_possible_amplitude else 0
    rep.peak_dbfs = 20 * math.log10(peak_ratio) if peak_ratio > 0 else float("-inf")
    rep.dynamic_range_db = rep.peak_dbfs - rep.rms_dbfs

    # Silence scan in 1-second windows (cap scan at first 30 min for huge files)
    window_ms = 1000
    total_windows = max(1, int(len(audio) / window_ms))
    scan_windows = min(total_windows, 1800)
    step = max(1, total_windows // scan_windows)
    silent = 0
    checked = 0
    for i in range(0, total_windows, step):
        chunk = audio[i * window_ms:(i + 1) * window_ms]
        checked += 1
        if chunk.dBFS < SILENCE_DBFS:
            silent += 1
    rep.silence_ratio = silent / checked if checked else 0.0

    rep.is_silent = rep.silence_ratio > 0.95
    rep.is_quiet = rep.rms_dbfs < -30.0
    rep.is_very_quiet = rep.rms_dbfs < -40.0
    rep.is_loud = rep.rms_dbfs > -12.0
    rep.is_clipped = audio.max >= audio.max_possible_amplitude * 0.99

    if rep.is_silent:
        rep.warnings.append("File is >95% silence — transcription will be mostly empty.")
    if rep.is_clipped:
        rep.warnings.append("Clipping detected — peaks are crushed; quality may suffer.")
    if rep.is_very_quiet:
        rep.warnings.append(f"Very quiet ({rep.rms_dbfs:.1f} dBFS) — strong gain boost needed.")
    if rep.channels > 1:
        rep.warnings.append(f"Stereo ({rep.channels}ch) — will downmix to mono for Whisper.")
    if rep.sample_rate != WHISPER_RATE:
        rep.warnings.append(f"Resampling {rep.sample_rate}Hz → {WHISPER_RATE}Hz for Whisper.")

    return rep


def recommend_target(report: AudioReport) -> Tuple[float, str]:
    """Pick a target RMS based on the analysis."""
    if report.is_very_quiet:
        return -16.0, "very quiet source — boosting harder for intelligibility"
    if report.is_quiet:
        return -18.0, "quiet source — normalising to speech level"
    if report.is_loud:
        return -14.0, "hot source — taming to leave headroom"
    return DEFAULT_TARGET_DBFS, "healthy level — standard speech target"


# ---------------------------------------------------------------------------
# Robust normalization pipeline
#   clean (highpass → mono → 16 kHz) → 2-pass gain → soft limit → verify
# ---------------------------------------------------------------------------

def clean_and_normalize(
    input_file: Path,
    output_folder: Path,
    target_dbfs: float = None,
    highpass: bool = True,
    max_gain_db: float = MAX_SAFE_GAIN_DB,
    keep_enhanced: bool = True,
    progress_cb: Callable = None,
) -> Tuple[Optional[Path], AudioReport, Optional[AudioReport]]:
    """
    Returns (enhanced_path_or_None, before_report, after_report_or_None).
    enhanced_path is None when the source was already optimal (nothing to fix).
    Raises RuntimeError on fatal audio problems (caller decides: abort or skip).
    """
    from pydub import AudioSegment

    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    _log("[AUDIO] ── audio pipeline ──")
    _log(f"[AUDIO] Loading: {input_file.name}")
    before = analyze_audio(input_file)
    _log(f"[AUDIO] Before: {before.summary()}")
    for w in before.warnings:
        _log(f"[WARN] {w}")
    if before.is_silent:
        raise RuntimeError("File is essentially silent — refusing to process.")

    if target_dbfs is None:
        target_dbfs, reason = recommend_target(before)
        _log(f"[AUDIO] Auto target: {target_dbfs:.0f} dBFS ({reason})")
    else:
        _log(f"[AUDIO] Manual target: {target_dbfs:.0f} dBFS")

    audio = AudioSegment.from_file(str(input_file))

    # — Pass 0: cleanup (always safe, always applied to the working copy) —
    if highpass:
        _log(f"[AUDIO] High-pass @ {HIGHPASS_HZ}Hz (removes rumble/hum/DC offset)…")
        audio = audio.high_pass_filter(HIGHPASS_HZ)
    if audio.channels > 1:
        _log("[AUDIO] Downmixing to mono…")
        audio = audio.set_channels(1)
    if audio.frame_rate != WHISPER_RATE:
        _log(f"[AUDIO] Resampling to {WHISPER_RATE}Hz…")
        audio = audio.set_frame_rate(WHISPER_RATE)

    # — Pass 1: coarse gain toward target —
    gain_needed = target_dbfs - audio.dBFS
    if abs(gain_needed) > max_gain_db:
        capped = max_gain_db if gain_needed > 0 else -max_gain_db
        _log(f"[WARN] Gain {gain_needed:+.1f}dB exceeds safe ±{max_gain_db:.0f}dB — capping at {capped:+.1f}dB")
        gain_needed = capped
        target_dbfs = audio.dBFS + gain_needed

    if abs(gain_needed) < 0.5 and not highpass and before.channels == 1 \
            and before.sample_rate == WHISPER_RATE:
        _log("[OK] Audio already optimal — no processing needed")
        return None, before, None

    _log(f"[AUDIO] Pass 1/2: applying {gain_needed:+.1f} dB gain…")
    audio = audio.apply_gain(gain_needed)

    # — Soft limiter: pull peaks down to -1 dBFS ceiling instead of clipping —
    peak_ratio = audio.max / audio.max_possible_amplitude if audio.max_possible_amplitude else 0
    peak_db = 20 * math.log10(peak_ratio) if peak_ratio > 0 else float("-inf")
    if peak_db > -1.0:
        _log(f"[AUDIO] Pass 2/2: limiting peaks ({peak_db:.1f} → -1.0 dBFS ceiling)…")
        audio = audio.apply_gain(-(peak_db + 1.0))
    else:
        _log("[AUDIO] Pass 2/2: peaks within ceiling — limiter idle")

    # — Export + verify (never trust the math; measure the file) —
    out = output_folder / f"{input_file.stem}_enhanced.wav"
    n = 1
    while out.exists():
        out = output_folder / f"{input_file.stem}_enhanced_{n}.wav"
        n += 1
    audio.export(str(out), format="wav")
    after = analyze_audio(out)

    problems = []
    if after.is_clipped:
        problems.append("output still clips")
    if abs(after.rms_dbfs - target_dbfs) > 3.0:
        problems.append(f"missed target by {abs(after.rms_dbfs - target_dbfs):.1f}dB")
    if after.is_silent:
        problems.append("output is silent — pipeline fault")
    if problems:
        cleanup_files([out])
        raise RuntimeError("Verification failed: " + "; ".join(problems))

    _log(f"[AUDIO] After:  {after.summary()}")
    _log(f"[OK] Enhanced audio saved: {out.name}")
    return out, before, after


# ---------------------------------------------------------------------------
# Transcript cleanup + beautiful formatting.
# Rule: never delete real words. Only fix mechanical artifacts:
#   - stray spaces before punctuation ("word ." → "word.")
#   - collapsed whitespace, sentence capitalization at paragraph starts
#   - exact-duplicate consecutive paragraphs (a known Whisper loop artifact)
# ---------------------------------------------------------------------------

_PUNCT_SPACE = re.compile(r'\s+([.,!?;:%])')
_MULTI_SPACE = re.compile(r'\s+')
_OPEN_BRACKET_SPACE = re.compile(r'([(“"‘])\s+')

LANG_NAMES = {v: k for k, v in LANGUAGES.items() if v}


def _clean_text(text: str) -> str:
    text = _MULTI_SPACE.sub(' ', text).strip()
    text = _PUNCT_SPACE.sub(r'\1', text)
    text = _OPEN_BRACKET_SPACE.sub(r'\1', text)
    text = re.sub(r'\.{2,}', '.', text)          # ".." / "..." stutters → "."
    text = re.sub(r'(.)\1{3,}', r'\1\1', text)   # "soooo" → "soo" (keeps emphasis, kills loops)
    return text.strip()


def _cap_first(text: str) -> str:
    for i, ch in enumerate(text):
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1:]
    return text


_ABBREV = {'e.g', 'i.e', 'etc', 'vs', 'dr', 'mr', 'mrs', 'ms', 'st',
           'fig', 'eq', 'sec', 'ch', 'no', 'approx', 'min', 'max', 'dept',
           'univ', 'u.s', 'u.k', 'a.m', 'p.m'}


def _fix_sentence_case(text: str) -> str:
    """Capitalize sentence starts, guarding common abbreviations."""
    text = _cap_first(text)

    def _rep(m):
        prev_word = re.search(r'([A-Za-z]+(?:\.[A-Za-z]+)*)\.$', m.group(1).rstrip())
        if prev_word and prev_word.group(1).lower() in _ABBREV:
            return m.group(0)
        return m.group(1) + m.group(2).upper()

    return re.sub(r'(.+?[.!?]\s+)([a-z])', _rep, text)


def _build_paragraphs(result, include_timestamps: bool, include_segments: bool = True) -> List[str]:
    """Segment-aware paragraphing → cleaned, timestamped paragraph strings."""
    raw_paras: List[Tuple[float, str]] = []  # (timestamp_sec, text)

    if include_segments and "segments" in result and result["segments"]:
        # Pre-clean segments + drop consecutive duplicates (Whisper loop artifact)
        segs: List[Tuple[float, float, str]] = []
        for seg in result["segments"]:
            t = _clean_text(seg.get("text", ""))
            if not t:
                continue
            if segs and t == segs[-1][2]:
                continue
            segs.append((seg["start"], seg["end"], t))

        buf: list[str] = []
        last_end = 0.0
        para_start = 0.0
        for i, (start, end, text) in enumerate(segs):
            gap = start - last_end if i > 0 else 0.0
            is_end = text.endswith(('.', '!', '?', ':', ';'))
            # Break on: long pause, sentence end + short pause, or runaway length
            if buf and (gap > 2.5 or (is_end and gap > 1.2) or len(" ".join(buf)) > 600):
                raw_paras.append((para_start, " ".join(buf)))
                buf = []
            if not buf:
                para_start = start
            else:
                # Missing punctuation at a join where the next segment starts a
                # new capitalized sentence → restore the period. Lectures rarely
                # continue mid-sentence with a capital letter.
                prev = buf[-1]
                if not prev.endswith(('.', '!', '?', ';', ':', ',')) and text[:1].isupper():
                    buf[-1] = prev + '.'
            buf.append(text)
            last_end = end
        if buf:
            raw_paras.append((para_start, " ".join(buf)))
    else:
        # Fallback: sentence-based chunking
        full = result.get("text", "").strip()
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', full) if s.strip()]
        buf = []
        for sent in sentences:
            buf.append(sent)
            if len(buf) >= 4 or len(" ".join(buf)) > 600:
                raw_paras.append((0.0, " ".join(buf)))
                buf = []
        if buf:
            raw_paras.append((0.0, " ".join(buf)))

    # Final polish + drop exact-duplicate consecutive paragraphs (belt & braces)
    paras: List[str] = []
    prev = None
    for ts, text in raw_paras:
        text = _fix_sentence_case(_clean_text(text))
        if not text or text == prev:
            continue
        prev = text
        prefix = f"[{format_timestamp(ts)}] " if include_timestamps else ""
        paras.append(f"{prefix}{text}")
    return paras


def format_transcript(result, include_timestamps=True, include_segments=True,
                      title: str = "Lecture", meta: dict = None) -> str:
    paras = _build_paragraphs(result, include_timestamps, include_segments)
    body = "\n\n".join(paras)

    lang = LANG_NAMES.get(result.get("language", ""), result.get("language", "Unknown"))
    dur_min = result.get("duration", 0) / 60
    words = len(re.findall(r"[A-Za-z0-9']+", body))
    read_min = max(1, round(words / 200))
    meta = meta or {}
    engine = meta.get("engine", "")
    bar = "=" * 78

    flagged = uncertain_segments(result)
    lines = [
        bar,
        title.upper(),
        bar,
        f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}  ·  "
        f"Language: {lang}  ·  Duration: {dur_min:.1f} min",
        f"Words: ~{words:,}  ·  ~{read_min} min read  ·  Paragraphs: {len(paras)}"
        + (f"  ·  Engine: {engine}" if engine else "")
        + (f"  ·  ⚠ {len(flagged)} to verify" if flagged else ""),
        bar,
        "",
        body,
    ]
    if flagged:
        lines += ["", "-" * 78,
                  f"SEGMENTS TO VERIFY ({len(flagged)}) — low model confidence, worth a re-listen:"]
        for seg in flagged[:MAX_FLAGGED]:
            lines.append(f"[{format_timestamp(seg.get('start', 0))}] "
                         f"\"{_clean_text(seg.get('text', ''))}\"")
        if len(flagged) > MAX_FLAGGED:
            lines.append(f"…and {len(flagged) - MAX_FLAGGED} more (see raw JSON).")
    lines += ["", bar,
              f"END — {len(paras)} paragraphs · generated by Auto Transcriber",
              bar]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# API providers — chunked transcription for long lectures
# ---------------------------------------------------------------------------

def _split_for_api(audio_path: Path, chunk_min: int, tmpdir: Path,
                   progress_cb: Callable = None) -> List[Tuple[Path, float]]:
    """Split into compressed mp3 chunks. Returns [(chunk_path, offset_sec)]."""
    from pydub import AudioSegment

    audio = AudioSegment.from_file(str(audio_path))
    chunk_ms = chunk_min * 60 * 1000
    out: List[Tuple[Path, float]] = []
    if len(audio) <= chunk_ms:
        return [(audio_path, 0.0)]
    n = (len(audio) + chunk_ms - 1) // chunk_ms
    if progress_cb:
        progress_cb(f"[API] Splitting into {n} × ~{chunk_min}min chunks (mp3 64k mono)…")
    for i in range(n):
        seg = audio[i * chunk_ms:(i + 1) * chunk_ms]
        cp = tmpdir / f"chunk_{i:03d}.mp3"
        seg.export(str(cp), format="mp3", bitrate="64k",
                   parameters=["-ac", "1", "-ar", "16000"])
        out.append((cp, i * chunk_ms / 1000.0))
    return out


def merge_chunk_results(chunks: List[Dict[str, Any]], offsets: List[float],
                        language: str = None) -> Dict[str, Any]:
    """Pure function: stitch per-chunk verbose_json into one Whisper-style result."""
    merged_text: List[str] = []
    merged_segments: List[Dict[str, Any]] = []
    duration = 0.0
    for res, off in zip(chunks, offsets):
        merged_text.append(res.get("text", "").strip())
        for seg in res.get("segments", []) or []:
            merged_segments.append({
                "id": len(merged_segments),
                "start": seg.get("start", 0) + off,
                "end": seg.get("end", 0) + off,
                "text": seg.get("text", ""),
            })
        duration = max(duration, off + res.get("duration", 0))
    if not language:
        language = chunks[0].get("language", "Unknown") if chunks else "Unknown"
    return {"text": " ".join(t for t in merged_text if t),
            "segments": merged_segments,
            "language": language,
            "duration": duration}


def transcribe_via_api(
    audio_path: Path,
    provider: str,
    api_key: str,
    model: str = None,
    language: str = None,
    chunk_min: int = API_CHUNK_MIN,
    retries: int = 3,
    progress_cb: Callable = None,
) -> Dict[str, Any]:
    """Transcribe via Groq/OpenAI with chunking, retries, and temp cleanup."""
    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    if provider == "groq":
        try:
            from groq import Groq
        except ImportError:
            raise RuntimeError("groq package missing — run: pip install groq")
        client = Groq(api_key=api_key)
        model = model or PROVIDERS["groq"]["default_model"]
        call = lambda f, m, lang: client.audio.transcriptions.create(
            file=f, model=m, language=lang,
            response_format="verbose_json", temperature=0.0)
    elif provider == "openai":
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("openai package missing — run: pip install openai")
        client = OpenAI(api_key=api_key)
        model = model or PROVIDERS["openai"]["default_model"]
        call = lambda f, m, lang: client.audio.transcriptions.create(
            file=f, model=m, language=lang,
            response_format="verbose_json", temperature=0.0)
    else:
        raise RuntimeError(f"Unknown API provider: {provider}")

    tmpdir = Path(tempfile.mkdtemp(prefix="at_chunks_"))
    try:
        chunks = _split_for_api(audio_path, chunk_min, tmpdir, progress_cb=_log)
        results, offsets = [], []
        for i, (cp, off) in enumerate(chunks, 1):
            size_mb = cp.stat().st_size / 1024 / 1024
            _log(f"[API] Chunk {i}/{len(chunks)} → {provider} ({model}, {size_mb:.1f} MB)…")
            last_err = None
            for attempt in range(1, retries + 1):
                try:
                    with open(cp, "rb") as f:
                        r = call(f, model, language)
                    d = r.model_dump() if hasattr(r, "model_dump") else dict(r)
                    results.append(d)
                    offsets.append(off)
                    _log(f"[OK] Chunk {i}/{len(chunks)} done")
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    _log(f"[WARN] Chunk {i} attempt {attempt}/{retries} failed: {e}")
                    time.sleep(2 * attempt)
            if last_err is not None:
                raise RuntimeError(f"Chunk {i} failed after {retries} tries: {last_err}")
        _log(f"[API] Stitching {len(results)} chunks…")
        return merge_chunk_results(results, offsets, language)
    finally:
        cleanup_files(tmpdir.glob("*.mp3"))
        try:
            tmpdir.rmdir()
        except OSError:
            pass


def test_api_key(provider: str, api_key: str) -> Tuple[bool, str]:
    """Validate a key with a cheap models-list call. Returns (ok, message)."""
    try:
        if provider == "groq":
            from groq import Groq
            models = Groq(api_key=api_key).models.list()
            names = [m.id for m in models.data or []]
            whisper = [n for n in names if "whisper" in n.lower()]
            return True, f"Connected — Whisper models: {', '.join(whisper) or 'none visible'}"
        if provider == "openai":
            from openai import OpenAI
            models = OpenAI(api_key=api_key).models.list()
            names = [m.id for m in models.data or []]
            ok = any("whisper" in n for n in names)
            return True, "Connected — Whisper available ✓" if ok else "Connected, but no Whisper access"
        return False, f"Unknown provider: {provider}"
    except ImportError as e:
        return False, f"SDK missing: {e} — pip install {provider}"
    except Exception as e:
        return False, f"Key rejected: {e}"


# ---------------------------------------------------------------------------
# faster-whisper engine + model-cache clarity + confidence + subtitles
# ---------------------------------------------------------------------------

MODEL_SIZES_GB = {"tiny": "75 MB", "base": "150 MB", "small": "500 MB",
                  "medium": "1.5 GB", "large-v2": "3 GB", "large-v3": "3 GB",
                  "whisper-large-v3-turbo": "1.6 GB", "whisper-large-v3": "3 GB",
                  "whisper-1": "n/a (cloud)"}


def model_cached(provider: str, model_name: str) -> bool:
    """True if the model weights are already on disk (no first-run download)."""
    home = Path.home()
    if provider == "local":
        return (home / ".cache" / "whisper" / f"{model_name}.pt").exists()
    if provider == "fast":
        d = home / ".cache" / "huggingface" / "hub" / f"models--Systran--faster-whisper-{model_name}"
        return d.is_dir() and any(d.iterdir())
    return True  # cloud providers hold the model


def warn_if_downloading(provider: str, model_name: str, progress_cb: Callable = None):
    if not model_cached(provider, model_name):
        size = MODEL_SIZES_GB.get(model_name, "?")
        if progress_cb:
            progress_cb(f"[WARN] First run — downloading {model_name} model (~{size}, one-time). "
                        f"This can take a while; later runs are instant.")


def transcribe_via_faster_whisper(
    audio_path: Path,
    model_name: str = "large-v3",
    language: str = None,
    device: str = "auto",
    progress_cb: Callable = None,
) -> Dict[str, Any]:
    """Same guards as local Whisper, ~4x faster via CTranslate2."""
    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise RuntimeError("faster-whisper missing — run: pip install faster-whisper")

    if device == "auto":
        device = "cuda" if check_cuda() else "cpu"
    compute = "float16" if device == "cuda" else "int8"
    _log(f"[STEP 3/4] Loading faster-whisper ({model_name}) on {device}/{compute}…")
    fw = WhisperModel(model_name, device=device, compute_type=compute)
    _log("[STEP 3/4] Transcribing (fast engine — watch it go)…")
    segments_gen, info = fw.transcribe(
        str(audio_path),
        language=language,
        task="transcribe",
        condition_on_previous_text=False,
        compression_ratio_threshold=2.4,
        log_prob_threshold=-1.0,
        no_speech_threshold=0.6,
        temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        initial_prompt="This is an English language lecture. "
                       "Transcribe only English speech with proper punctuation.",
    )
    segs = [{"start": float(s.start), "end": float(s.end), "text": s.text,
             "avg_logprob": float(s.avg_logprob),
             "no_speech_prob": float(s.no_speech_prob)}
            for s in segments_gen]
    return {"text": " ".join(s["text"].strip() for s in segs),
            "segments": segs,
            "language": info.language,
            "duration": float(info.duration)}


UNCERTAIN_LOGPROB = -0.8  # avg_logprob below this ⇒ worth a re-listen
MAX_FLAGGED = 30


def uncertain_segments(result: Dict[str, Any],
                       threshold: float = UNCERTAIN_LOGPROB) -> List[Dict[str, Any]]:
    """Segments the model itself scored as shaky. Empty list if unscored."""
    out = []
    for seg in result.get("segments", []) or []:
        lp = seg.get("avg_logprob")
        if lp is None:
            continue
        try:
            if float(lp) < threshold:
                out.append(seg)
        except (TypeError, ValueError):
            continue
    return out


def _srt_stamp(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    return f"{ms//3600000:02d}:{(ms//60000)%60:02d}:{(ms//1000)%60:02d},{ms%1000:03d}"


def _wrap_sub(text: str, width: int = 84) -> str:
    if len(text) <= width:
        return text
    cut = text.rfind(" ", 0, width)
    cut = cut if cut > width // 2 else width
    return text[:cut].rstrip() + "\n" + text[cut:].strip()


def write_srt(segments: List[Dict[str, Any]], path: Path):
    lines = []
    n = 0
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        n += 1
        lines += [str(n),
                  f"{_srt_stamp(seg.get('start', 0))} --> {_srt_stamp(seg.get('end', 0))}",
                  _wrap_sub(text), ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_vtt(segments: List[Dict[str, Any]], path: Path):
    lines = ["WEBVTT", ""]
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        lines += [f"{_srt_stamp(seg.get('start', 0)).replace(',', '.')} --> "
                  f"{_srt_stamp(seg.get('end', 0)).replace(',', '.')}",
                  _wrap_sub(text), ""]
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main transcription entry points
# ---------------------------------------------------------------------------

def transcribe_file(
    input_file: Path,
    processed_folder: Path,
    model_name: str = "large-v3",
    language: str = None,
    normalize: bool = True,
    include_timestamps: bool = True,
    include_segments: bool = True,
    device: str = "auto",
    provider: str = "local",
    api_key: str = None,
    target_dbfs: float = None,
    highpass: bool = True,
    progress_cb: Callable = None,
) -> dict:
    t0 = time.time()

    def _log(msg):
        if progress_cb:
            progress_cb(msg)

    base_name = input_file.stem
    lecture_dir = processed_folder / base_name
    lecture_dir.mkdir(parents=True, exist_ok=True)

    _log(f"[STEP 1/4] Input: {input_file.name} ({input_file.stat().st_size/1024/1024:.1f} MB)")

    # — audio pipeline —
    _log("[STEP 2/4] Audio pipeline…")
    audio_file = input_file
    enhanced = None
    audio_info: Dict[str, Any] = {}
    if normalize:
        try:
            enhanced, before, after = clean_and_normalize(
                input_file, lecture_dir, target_dbfs=target_dbfs,
                highpass=highpass, progress_cb=_log)
            audio_info = {"before": before.summary(),
                          "after": after.summary() if after else "unchanged (already optimal)"}
            if enhanced:
                audio_file = enhanced
        except RuntimeError as e:
            _log(f"[ERR] Audio pipeline: {e}")
            raise
    else:
        try:
            rep = analyze_audio(input_file)
            audio_info = {"before": rep.summary(), "after": "skipped (normalization off)"}
            _log(f"[AUDIO] {rep.summary()} (normalization disabled)")
        except RuntimeError as e:
            _log(f"[ERR] {e}")
            raise

    # — transcription —
    _log("[STEP 3/4] Transcription…")
    key = resolve_api_key(provider, api_key)
    if provider in ("groq", "openai"):
        if not key:
            raise RuntimeError(
                f"No API key for {provider}. Add one in the app settings or set "
                f"{PROVIDERS[provider]['env_var']}.")
        _log(f"[API] Provider: {provider} · model: {model_name}")
        wp_result = transcribe_via_api(
            audio_file, provider, key, model=model_name,
            language=language, progress_cb=_log)
    elif provider == "fast":
        warn_if_downloading("fast", model_name, _log)
        wp_result = transcribe_via_faster_whisper(
            audio_file, model_name=model_name, language=language,
            device=device, progress_cb=_log)
    else:
        import whisper
        if device == "auto":
            device = "cuda" if check_cuda() else "cpu"
        warn_if_downloading("local", model_name, _log)
        _log(f"[STEP 3/4] Loading local Whisper ({model_name}) on {device}…")
        model = whisper.load_model(model_name, device=device)
        _log("[STEP 3/4] Transcribing (this is the slow part — watch GPU/CPU)…")
        wp_result = model.transcribe(
            str(audio_file),
            language=language,
            verbose=False,
            task="transcribe",
            fp16=(device == "cuda"),
            # Accuracy guards: never let one bad window poison the rest,
            # retry failed windows at higher temperatures, drop low-confidence
            # and repetitive (hallucinated) segments.
            condition_on_previous_text=False,
            temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
            compression_ratio_threshold=2.4,
            logprob_threshold=-1.0,
            no_speech_threshold=0.6,
            initial_prompt="This is an English language lecture. "
                           "Transcribe only English speech with proper punctuation.",
        )

    # — format & save —
    _log("[STEP 4/4] Formatting + saving…")
    engine = (f"{provider} {model_name}" if provider in ("local", "fast")
              else f"{provider}/{model_name}")
    formatted = format_transcript(wp_result, include_timestamps, include_segments,
                                  title=base_name, meta={"engine": engine})
    transcript_path = lecture_dir / f"{base_name}_transcript.txt"
    json_path = lecture_dir / f"{base_name}_transcript_raw.json"
    srt_path = lecture_dir / f"{base_name}.srt"
    vtt_path = lecture_dir / f"{base_name}.vtt"
    transcript_path.write_text(formatted, encoding="utf-8")
    json_path.write_text(json.dumps(wp_result, indent=2, ensure_ascii=False), encoding="utf-8")
    write_srt(wp_result.get("segments", []) or [], srt_path)
    write_vtt(wp_result.get("segments", []) or [], vtt_path)
    _log(f"[OK] Saved: {transcript_path.name} + {srt_path.name} + {vtt_path.name}")

    elapsed = time.time() - t0
    stats = {
        "language": wp_result.get("language", "Unknown"),
        "duration_min": round(wp_result.get("duration", 0) / 60, 1),
        "chars": len(formatted),
        "uncertain": len(uncertain_segments(wp_result)),
        "elapsed_min": round(elapsed / 60, 1),
        "provider": provider,
    }
    _log(f"[OK] Done in {elapsed/60:.1f} min — {stats['duration_min']} min audio, "
         f"{stats['chars']} chars → {transcript_path.name}")

    return {
        "transcript_text": formatted,
        "transcript_path": str(transcript_path),
        "json_path": str(json_path),
        "srt_path": str(srt_path),
        "vtt_path": str(vtt_path),
        "enhanced_path": str(enhanced) if enhanced else None,
        "audio": audio_info,
        "stats": stats,
    }


def transcribe_queue(
    queue_folder: Path,
    processed_folder: Path,
    model_name: str = "large-v3",
    language: str = None,
    normalize: bool = True,
    include_timestamps: bool = True,
    include_segments: bool = True,
    device: str = "auto",
    provider: str = "local",
    api_key: str = None,
    target_dbfs: float = None,
    highpass: bool = True,
    archive_dir: Path = None,
    progress_cb: Callable = None,
) -> dict:
    files = get_audio_files(queue_folder)
    if not files:
        if progress_cb:
            progress_cb("[WARN] Queue is empty — drop files into queue/ and retry.")
        return {"total": 0, "successful": 0, "failed": 0, "results": []}

    if progress_cb:
        progress_cb(f"[STEP 0/4] {len(files)} file(s) queued · provider={provider} · model={model_name}")

    results, successful, failed = [], 0, 0
    for i, f in enumerate(files, 1):
        def _log(msg, _f=f, _i=i, _n=len(files)):
            if progress_cb:
                progress_cb(f"[{_i}/{_n} {Path(_f).name}] {msg}")
        try:
            r = transcribe_file(
                f, processed_folder, model_name=model_name, language=language,
                normalize=normalize, include_timestamps=include_timestamps,
                include_segments=include_segments, device=device, provider=provider,
                api_key=api_key, target_dbfs=target_dbfs, highpass=highpass,
                progress_cb=_log)
            if archive_dir is not None:
                try:
                    dest = archive_original(f, archive_dir)
                    _log(f"[OK] Original archived → archive/{dest.parent.name}/{dest.name}")
                except Exception as e:
                    _log(f"[WARN] Could not archive original: {e}")
            results.append({"file": f.name, "ok": True, **r["stats"]})
            successful += 1
        except Exception as e:
            if progress_cb:
                progress_cb(f"[{i}/{len(files)} {f.name}] [ERR] {e}")
            results.append({"file": f.name, "ok": False, "error": str(e)})
            failed += 1

    return {"total": len(files), "successful": successful,
            "failed": failed, "results": results}


# ---------------------------------------------------------------------------
# Zip archiving
# ---------------------------------------------------------------------------

def archive_to_zip(original_file: Path, zip_path: Path, class_code: str) -> bool:
    try:
        mode = 'a' if zip_path.exists() else 'w'
        with zipfile.ZipFile(zip_path, mode, zipfile.ZIP_DEFLATED) as zf:
            zf.write(original_file, f"{class_code}/{original_file.name}")
        return True
    except Exception:
        return False


def archive_original(src: Path, archive_dir: Path) -> Path:
    """Move a finished original into archive/<ClassCode>/ (collision-safe)."""
    dest_dir = archive_dir / extract_class_code(src.name)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    n = 1
    while dest.exists():
        dest = dest_dir / f"{src.stem}_{n}{src.suffix}"
        n += 1
    shutil.move(str(src), str(dest))
    return dest


def maybe_ping_ntfy(subject: str, message: str) -> bool:
    """POST a phone notification via ntfy if NTFY_TOPIC is configured.

    Env: NTFY_URL (default https://ntfy.sh), NTFY_TOPIC (unset = silent no-op).
    Never raises — returns True only if the ping was accepted.
    """
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return False
    url = os.environ.get("NTFY_URL", "https://ntfy.sh").rstrip("/")
    try:
        req = urllib.request.Request(
            f"{url}/{topic}", data=message.encode("utf-8"),
            headers={"Title": subject[:200]}, method="POST")
        with urllib.request.urlopen(req, timeout=10):
            pass
        return True
    except Exception:
        return False
