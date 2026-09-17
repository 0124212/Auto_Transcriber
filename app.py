#!/usr/bin/env python3
"""
Auto Transcriber — Flask web UI.
Cross-platform: works identically on Windows, macOS, and Linux.
"""

import os
import shutil
import subprocess
import sys
import json
import queue
import threading
import webbrowser
from pathlib import Path
from datetime import datetime

from flask import Flask, render_template, request, jsonify, Response, send_from_directory

from core import (
    PRESETS, LANGUAGES, MODEL_SIZES, PROVIDERS,
    get_audio_files, transcribe_file, transcribe_queue,
    resolve_api_key, test_api_key, archive_original,
    extract_class_code, maybe_ping_ntfy,
)

app = Flask(__name__)
app.secret_key = os.urandom(24)

BASE_DIR = Path(__file__).parent.resolve()
QUEUE_DIR = BASE_DIR / "queue"
PROCESSED_DIR = BASE_DIR / "processed"
ARCHIVE_DIR = BASE_DIR / "archive"
QUEUE_DIR.mkdir(exist_ok=True)
PROCESSED_DIR.mkdir(exist_ok=True)
ARCHIVE_DIR.mkdir(exist_ok=True)

# Copy-with-prompt packs: id -> prompt file (allowlist, never user paths)
PROMPTS = {
    "cheat": "prompt_cheat_sheet.md",
    "notes": "prompt_condensed_notes.md",
    "summary": "prompt_descriptive_summary.md",
}

# SSE progress channels: one queue per client session
_progress_channels: dict[str, queue.Queue] = {}


def _make_channel() -> str:
    import uuid
    ch = uuid.uuid4().hex[:12]
    _progress_channels[ch] = queue.Queue()
    return ch


def _emit(channel: str, event: str, data: str):
    q = _progress_channels.get(channel)
    if q:
        q.put(f"event: {event}\ndata: {data}\n\n")


# ── Routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html",
                           presets=PRESETS,
                           languages=list(LANGUAGES.keys()),
                           models=MODEL_SIZES,
                           providers=PROVIDERS)


@app.route("/api/queue")
def api_queue():
    files = get_audio_files(QUEUE_DIR)
    out = []
    for f in files:
        done = (PROCESSED_DIR / f.stem / f"{f.stem}_transcript.txt").exists()
        out.append({"name": f.name, "size": f.stat().st_size, "done": done})
    return jsonify(out)


def _queue_target(filename: str) -> Path | None:
    """Resolve a queue filename, confined to QUEUE_DIR. None if illegal."""
    target = (QUEUE_DIR / filename).resolve()
    if QUEUE_DIR.resolve() not in target.parents or not target.is_file():
        return None
    return target


@app.route("/api/queue/<path:filename>", methods=["DELETE"])
def api_queue_delete(filename):
    target = _queue_target(filename)
    if target is None:
        return jsonify(error="not found"), 404
    target.unlink()
    return jsonify(deleted=filename)


@app.route("/api/queue/clear", methods=["POST"])
def api_queue_clear():
    removed = 0
    for f in get_audio_files(QUEUE_DIR):
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    return jsonify(cleared=removed)


def _probe_minutes(path: Path) -> float | None:
    """Audio duration in minutes via ffprobe (instant, no decode)."""
    if not shutil.which("ffprobe"):
        return None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=15)
        return float(r.stdout.strip()) / 60
    except (ValueError, subprocess.SubprocessError, OSError):
        return None


OPENAI_USD_PER_MIN = 0.006


@app.route("/api/estimate")
def api_estimate():
    """Cost/time clarity: queue durations + what each engine costs. Free unless OpenAI."""
    files = []
    total = 0.0
    unknown = False
    for f in get_audio_files(QUEUE_DIR):
        mins = _probe_minutes(f)
        if mins is None:
            unknown = True
        else:
            total += mins
        files.append({"name": f.name, "minutes": round(mins, 1) if mins else None})
    return jsonify({
        "files": files,
        "total_min": round(total, 1),
        "unknown": unknown,
        "costs": {
            "local": 0.0,
            "fast": 0.0,
            "groq": 0.0,
            "openai": round(total * OPENAI_USD_PER_MIN, 2),
        },
    })


@app.route("/api/processed")
def api_processed():
    folders = []
    if PROCESSED_DIR.exists():
        for d in sorted(PROCESSED_DIR.iterdir()):
            if d.is_dir():
                outputs = sorted(
                    [t.name for t in d.iterdir()
                     if t.is_file() and t.suffix in (".txt", ".srt", ".vtt", ".md")])
                # transcript first, then the rest
                outputs.sort(key=lambda n: (0 if n.endswith("_transcript.txt") else 1, n))
                folders.append({"name": d.name, "transcripts": outputs})
    return jsonify(folders)


VIEWABLE = {".txt", ".srt", ".vtt", ".md"}


@app.route("/api/transcript/<path:folder>/<path:filename>")
def api_transcript(folder, filename):
    f = PROCESSED_DIR / folder / filename
    if f.exists() and f.suffix in VIEWABLE:
        return Response(f.read_text(encoding="utf-8"), mimetype="text/plain")
    return jsonify(error="not found"), 404


@app.route("/api/upload", methods=["POST"])
def api_upload():
    uploaded = request.files.getlist("files")
    saved = []
    for f in uploaded:
        if f.filename:
            dest = QUEUE_DIR / f.filename
            f.save(str(dest))
            saved.append(f.filename)
    return jsonify(saved=saved)


def _parse_common(body: dict) -> dict:
    """Shared transcribe options from request JSON."""
    preset = body.get("preset", "balanced")
    provider = body.get("provider", "local")
    model = body.get("model") or PROVIDERS.get(provider, {}).get(
        "default_model", PRESETS.get(preset, {}).get("model", "large-v3"))
    lang_name = body.get("language", "Auto-detect")
    return {
        "model": model,
        "language": LANGUAGES.get(lang_name),
        "normalize": body.get("normalize", True),
        "timestamps": body.get("timestamps", True),
        "segments": body.get("segments", True),
        "device": body.get("device", "auto"),
        "provider": provider,
        "api_key": body.get("api_key") or None,
        "target_dbfs": body.get("target_dbfs"),
        "highpass": body.get("highpass", True),
        "channel": body.get("channel"),
    }


@app.route("/api/providers")
def api_providers():
    """List providers + whether a key is configured (never exposes the key)."""
    out = {}
    for pid, p in PROVIDERS.items():
        out[pid] = {
            "label": p["label"],
            "needs_key": p["needs_key"],
            "models": p["models"],
            "default_model": p["default_model"],
            "key_url": p.get("key_url"),
            "key_configured": bool(resolve_api_key(pid)) if p["needs_key"] else True,
        }
    return jsonify(out)


@app.route("/api/key", methods=["POST"])
def api_key_save():
    """Save an API key to .env (chmod 600). Body: {provider, key}."""
    body = request.json or {}
    provider = body.get("provider")
    key = (body.get("key") or "").strip()
    if provider not in PROVIDERS or not PROVIDERS[provider]["needs_key"]:
        return jsonify(error="unknown provider"), 400
    if not key:
        return jsonify(error="empty key"), 400
    env_var = PROVIDERS[provider]["env_var"]
    env_path = BASE_DIR / ".env"
    lines = []
    if env_path.exists():
        lines = [l for l in env_path.read_text().splitlines()
                 if not l.startswith(env_var + "=")]
    lines.append(f"{env_var}={key}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(env_path, 0o600)
    except OSError:
        pass
    os.environ[env_var] = key  # live for this process too
    return jsonify(saved=True)


@app.route("/api/key/test", methods=["POST"])
def api_key_test():
    """Cheap validation of a key. Body: {provider, key?} (falls back to env)."""
    body = request.json or {}
    provider = body.get("provider")
    if provider not in PROVIDERS:
        return jsonify(error="unknown provider"), 400
    key = (body.get("key") or "").strip() or resolve_api_key(provider)
    if not key:
        return jsonify(ok=False, message="No key provided or configured.")
    ok, message = test_api_key(provider, key)
    return jsonify(ok=ok, message=message)


@app.route("/api/transcribe", methods=["POST"])
def api_transcribe():
    body = request.json or {}
    opts = _parse_common(body)
    channel = opts.pop("channel")

    def _progress(msg):
        if channel:
            _emit(channel, "progress", msg)

    def _run():
        try:
            if channel:
                _emit(channel, "started", "Processing started")
            result = transcribe_queue(
                QUEUE_DIR, PROCESSED_DIR,
                model_name=opts["model"], language=opts["language"],
                normalize=opts["normalize"], include_timestamps=opts["timestamps"],
                include_segments=opts["segments"], device=opts["device"],
                provider=opts["provider"], api_key=opts["api_key"],
                target_dbfs=opts["target_dbfs"], highpass=opts["highpass"],
                archive_dir=ARCHIVE_DIR,
                progress_cb=_progress,
            )
            result["ping"] = maybe_ping_ntfy(
                "Transcription done",
                f"{result['successful']}/{result['total']} files transcribed")
            if channel:
                _emit(channel, "done", json.dumps(result))
        except Exception as e:
            if channel:
                _emit(channel, "error", str(e))

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify(status="started")


@app.route("/api/transcribe/file", methods=["POST"])
def api_transcribe_file():
    """Transcribe a single file from the queue by name."""
    body = request.json or {}
    filename = body.get("filename")
    if not filename:
        return jsonify(error="filename required"), 400

    src = QUEUE_DIR / filename
    if not src.exists():
        return jsonify(error="file not found in queue"), 404

    opts = _parse_common(body)
    channel = opts.pop("channel")

    def _progress(msg):
        if channel:
            _emit(channel, "progress", msg)

    def _run():
        try:
            if channel:
                _emit(channel, "started", f"Transcribing {filename}")
            result = transcribe_file(
                src, PROCESSED_DIR,
                model_name=opts["model"], language=opts["language"],
                normalize=opts["normalize"], include_timestamps=opts["timestamps"],
                include_segments=opts["segments"], device=opts["device"],
                provider=opts["provider"], api_key=opts["api_key"],
                target_dbfs=opts["target_dbfs"], highpass=opts["highpass"],
                progress_cb=_progress,
            )
            try:
                dest = archive_original(src, ARCHIVE_DIR)
                _progress(f"[OK] Original archived → archive/{dest.parent.name}/{dest.name}")
            except Exception as e:
                _progress(f"[WARN] Could not archive original: {e}")
            ping = maybe_ping_ntfy("Transcription done", f"{filename} transcribed")
            if channel:
                _emit(channel, "done", json.dumps({
                    "file": filename,
                    "ok": True,
                    "ping": ping,
                    **result["stats"],
                }))
        except Exception as e:
            if channel:
                _emit(channel, "error", str(e))

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify(status="started")


@app.route("/api/prompts")
def api_prompts():
    """Copy-with-prompt choices: transcript-only + prompt templates."""
    out = [{"id": "none", "title": "Transcript only"}]
    for pid, fname in PROMPTS.items():
        title = pid
        try:
            first = (BASE_DIR / fname).read_text(encoding="utf-8").splitlines()[0]
            title = first.lstrip("# ").strip() or pid
        except OSError:
            pass
        out.append({"id": pid, "title": title})
    return jsonify(out)


@app.route("/api/pack")
def api_pack():
    """Combined copy pack: prompt template + transcript, ready to paste into AI."""
    folder = request.args.get("folder", "")
    file = request.args.get("file", "")
    prompt = request.args.get("prompt", "none")

    target = (PROCESSED_DIR / folder / file).resolve()
    if (PROCESSED_DIR.resolve() not in target.parents
            or target.suffix != ".txt" or not target.is_file()):
        return jsonify(error="not found"), 404
    text = target.read_text(encoding="utf-8")

    if prompt != "none":
        fname = PROMPTS.get(prompt)
        if not fname:
            return jsonify(error="unknown prompt"), 400
        pfile = (BASE_DIR / fname).resolve()
        if BASE_DIR.resolve() not in pfile.parents or not pfile.is_file():
            return jsonify(error="prompt missing"), 404
        pack = (pfile.read_text(encoding="utf-8").rstrip()
                + f"\n\n---\n\n# TRANSCRIPT: {file}\n\n" + text)
    else:
        pack = text
    return Response(pack, mimetype="text/plain")


@app.route("/api/sse/<channel>")
def api_sse(channel):
    def generate():
        q = _progress_channels.get(channel)
        if not q:
            return
        try:
            while True:
                item = q.get(timeout=300)
                if item is None:
                    break
                yield item
        except queue.Empty:
            pass
        finally:
            _progress_channels.pop(channel, None)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Main ────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Auto Transcriber Web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    print(f"\n  Auto Transcriber")
    print(f"  ────────────────────────────────")
    print(f"  Open: {url}")
    print(f"  Queue: {QUEUE_DIR}")
    print(f"  Output: {PROCESSED_DIR}")
    print()

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
