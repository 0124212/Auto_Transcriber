#!/usr/bin/env python3
"""
Auto Transcriber — Flask web UI.
Cross-platform: works identically on Windows, macOS, and Linux.
"""

import os
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
    resolve_api_key, test_api_key,
)

app = Flask(__name__)
app.secret_key = os.urandom(24)

BASE_DIR = Path(__file__).parent.resolve()
QUEUE_DIR = BASE_DIR / "queue"
PROCESSED_DIR = BASE_DIR / "processed"
QUEUE_DIR.mkdir(exist_ok=True)
PROCESSED_DIR.mkdir(exist_ok=True)

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
    return jsonify([{"name": f.name, "size": f.stat().st_size} for f in files])


@app.route("/api/processed")
def api_processed():
    folders = []
    if PROCESSED_DIR.exists():
        for d in sorted(PROCESSED_DIR.iterdir()):
            if d.is_dir():
                transcripts = list(d.glob("*_transcript.txt"))
                folders.append({
                    "name": d.name,
                    "transcripts": [t.name for t in transcripts],
                })
    return jsonify(folders)


@app.route("/api/transcript/<path:folder>/<path:filename>")
def api_transcript(folder, filename):
    f = PROCESSED_DIR / folder / filename
    if f.exists() and f.suffix == ".txt":
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
                progress_cb=_progress,
            )
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
            if channel:
                _emit(channel, "done", json.dumps({
                    "file": filename,
                    "ok": True,
                    **result["stats"],
                }))
        except Exception as e:
            if channel:
                _emit(channel, "error", str(e))

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify(status="started")


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
