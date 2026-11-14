#!/usr/bin/env python3
"""
analyze_video.py - turn a short video into evidence a language model can judge.

A model cannot watch or hear a video file directly, so this script extracts the
things that matter for a scroll-stopping judgment and writes them to disk:

  hook_sheet.jpg      dense contact sheet of the first seconds (the hook)
  timeline_sheet.jpg  evenly spaced frames across the whole video
  frames/             individual frames at higher resolution (read on-screen text)
  analysis.json       pacing (cuts and abrupt changes), motion, audio envelope, transcript, flags

Usage:
  python analyze_video.py VIDEO --out OUT_DIR
  python analyze_video.py --check          # report which dependencies are available

Requires: ffmpeg + ffprobe on PATH, numpy, Pillow.
Optional, for a speech transcript: sherpa-onnx (model from GitHub releases), faster-whisper or openai-whisper.
"""
import argparse
import importlib.util
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK_TIMES = [0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0]
SHEET_LONG_EDGE = 1560          # keeps sheets inside what vision models read at full fidelity
SCENE_THRESHOLD = 0.30          # ffmpeg scene-change score; 0.3-0.5 is the usual range
SILENCE_FLOOR_DB = -50.0
# Speech-to-text engines, in the order they are tried. The first two give true word timings but fetch their
# models from Hugging Face or Azure; sherpa-onnx fetches Whisper from GitHub releases, which is reachable in
# sandboxes that only allow package registries and GitHub.
ENGINES = (("faster_whisper", "faster-whisper"), ("whisper", "openai-whisper"), ("sherpa_onnx", "sherpa-onnx"))
SHERPA_MODELS_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"


# ----------------------------------------------------------------------------- utils
def have(binary):
    return shutil.which(binary) is not None


def run(cmd, binary_out=False, timeout=900):
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if binary_out:
        return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", "replace")
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


def installed(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def check_environment():
    report = {"ffmpeg": have("ffmpeg"), "ffprobe": have("ffprobe")}
    for module in ("numpy", "PIL"):
        report[module] = installed(module)
    report["speech_engines"] = [label for module, label in ENGINES if installed(module)]
    report["transcription"] = bool(report["speech_engines"])
    report["ready"] = all(report[k] for k in ("ffmpeg", "ffprobe", "numpy", "PIL"))
    return report


def print_environment(report):
    print("Environment check")
    for key in ("ffmpeg", "ffprobe", "numpy", "PIL"):
        print(f"  {'OK ' if report[key] else 'MISSING'}  {key} (required)")
    engines = ", ".join(report["speech_engines"]) or "none installed"
    print(f"  {'OK ' if report['transcription'] else '-- '}  speech-to-text (optional): {engines}")
    if not report["ready"]:
        print("\nInstall what is missing: ffmpeg from https://ffmpeg.org (or your package manager), "
              "and `pip install numpy pillow`.")
    if not report["transcription"]:
        print("\nNo speech-to-text engine. To get the spoken words automatically, install one:\n"
              "  pip install sherpa-onnx      fetches Whisper from GitHub releases; works where only package\n"
              "                               registries and GitHub are reachable\n"
              "  pip install faster-whisper   exact word timings; fetches its model from Hugging Face\n"
              "Without one, pass --transcript-file or read burned-in captions off the frames.")
    elif report["speech_engines"] == ["faster-whisper"] or report["speech_engines"] == ["openai-whisper"]:
        print("\nIf model downloads are blocked here, also `pip install sherpa-onnx`: it is tried as a fallback "
              "and fetches its model from GitHub.")


# ----------------------------------------------------------------------------- probing
def probe(path):
    code, out, err = run(["ffprobe", "-v", "error", "-print_format", "json",
                          "-show_format", "-show_streams", str(path)])
    if code != 0:
        sys.exit(f"ffprobe could not read {path}: {err.strip()[:300]}")
    info = json.loads(out)
    vstreams = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    astreams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not vstreams:
        sys.exit("No video stream found in the file.")
    v = vstreams[0]
    width, height = int(v.get("width", 0)), int(v.get("height", 0))
    rotation = 0
    for side in v.get("side_data_list", []) or []:
        if "rotation" in side:
            try:
                rotation = int(float(side["rotation"]))
            except (TypeError, ValueError):
                pass
    try:
        rotation = rotation or int(float((v.get("tags") or {}).get("rotate", 0)))
    except (TypeError, ValueError):
        pass
    if abs(rotation) % 180 == 90:
        width, height = height, width

    def frac(text):
        try:
            a, b = text.split("/")
            return float(a) / float(b) if float(b) else 0.0
        except Exception:
            return 0.0

    duration = 0.0
    for candidate in (info.get("format", {}).get("duration"), v.get("duration")):
        try:
            duration = float(candidate)
            if duration > 0:
                break
        except (TypeError, ValueError):
            continue
    ratio = width / height if height else 1.0
    orientation = "vertical" if ratio < 0.9 else ("square" if ratio <= 1.1 else "horizontal")
    try:
        bitrate = round(float(info.get("format", {}).get("bit_rate", 0)) / 1000)
    except (TypeError, ValueError):
        bitrate = None
    return {
        "duration_s": round(duration, 3),
        "width": width,
        "height": height,
        "orientation": orientation,
        "fps": round(frac(v.get("avg_frame_rate", "0/1")), 2),
        "has_audio": bool(astreams),
        "bitrate_kbps": bitrate,
        "codec": v.get("codec_name"),
    }


# ----------------------------------------------------------------------------- frames + sheets
def extract_frame(video, t, out_path, max_w=720):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
           "-vf", f"scale='min({max_w},iw)':-2", "-q:v", "3", "-y", str(out_path)]
    run(cmd)
    return out_path.exists() and out_path.stat().st_size > 0


def best_grid(n, tile_aspect):
    """Pick the column count that gives the largest tiles inside the long-edge budget."""
    best = None
    for cols in range(1, max(2, n) + 1):
        rows = math.ceil(n / cols)
        tile_w = min(SHEET_LONG_EDGE / cols, SHEET_LONG_EDGE / (rows * tile_aspect))
        if best is None or tile_w > best[0] + 1e-9:
            best = (tile_w, cols, rows)
    return int(min(best[0], 640)), best[1], best[2]


def contact_sheet(frames, labels, out_path):
    from PIL import Image, ImageDraw, ImageFont
    images = [Image.open(p).convert("RGB") for p in frames]
    if not images:
        return None
    w0, h0 = images[0].size
    aspect = h0 / w0
    tile_w, cols, rows = best_grid(len(images), aspect)
    tile_h = int(round(tile_w * aspect))
    pad = 4
    sheet = Image.new("RGB", (cols * tile_w + (cols + 1) * pad, rows * tile_h + (rows + 1) * pad), (18, 18, 18))
    draw = ImageDraw.Draw(sheet)
    font_size = max(14, tile_w // 14)
    try:
        font = ImageFont.load_default(size=font_size)
    except TypeError:                      # Pillow < 10.1
        font = ImageFont.load_default()
    for i, (img, label) in enumerate(zip(images, labels)):
        tile = img.resize((tile_w, tile_h))
        x = pad + (i % cols) * (tile_w + pad)
        y = pad + (i // cols) * (tile_h + pad)
        sheet.paste(tile, (x, y))
        box = draw.textbbox((0, 0), label, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        draw.rectangle([x, y, x + tw + 12, y + th + 12], fill=(0, 0, 0))
        draw.text((x + 6, y + 4), label, fill=(255, 235, 59), font=font)
    sheet.save(out_path, quality=88)
    return out_path


# ----------------------------------------------------------------------------- pacing
def scene_cuts(video, limit_s):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "info", "-t", f"{limit_s:.3f}", "-i", str(video),
           "-vf", f"scale=320:-2,select='gt(scene,{SCENE_THRESHOLD})',showinfo", "-an", "-f", "null", "-"]
    _, _, err = run(cmd)
    cuts = sorted({round(float(m), 2) for m in re.findall(r"pts_time:([0-9.]+)", err)})
    return [c for c in cuts if c > 0.05]


def abrupt_changes(video, meta, limit_s, fps=12, width=48):
    """Moments where the picture changes abruptly: cuts, jump cuts and hard graphic changes.

    The scene detector above misses cuts between similar-looking shots (a jump cut in a talking-head
    video), so this looks for spikes in frame-to-frame colour difference relative to the motion around them.
    """
    import numpy as np
    h = max(2, int(round(width * meta["height"] / max(meta["width"], 1) / 2)) * 2)
    cmd = ["ffmpeg", "-v", "error", "-t", f"{limit_s:.3f}", "-i", str(video),
           "-vf", f"fps={fps},scale={width}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    code, raw, _ = run(cmd, binary_out=True)
    size = width * h * 3
    n = len(raw) // size
    if code != 0 or n < 3:
        return []
    frames = np.frombuffer(raw[: n * size], dtype=np.uint8).reshape(n, h, width, 3)
    d = np.abs(frames[1:].astype(np.int16) - frames[:-1].astype(np.int16)).mean(axis=(1, 2, 3)) / 255.0
    out = []
    for t in range(len(d)):
        lo, hi = max(0, t - fps), min(len(d), t + fps + 1)
        around = np.concatenate([d[lo:max(lo, t - 1)], d[min(hi, t + 2):hi]])
        calm = float(np.median(around)) if len(around) else 0.0
        is_peak = d[t] >= d[max(0, t - 2): t + 3].max()
        if is_peak and ((d[t] >= 0.03 and d[t] >= 5 * calm + 0.01) or (d[t] >= 0.12 and d[t] >= 2.5 * calm)):
            out.append(round((t + 1) / fps, 2))
    return out


def pacing_stats(cuts, changes, duration):
    merged = []
    for t in sorted(set(cuts) | set(changes)):
        if not merged or t - merged[-1] > 0.3:
            merged.append(t)
    edges = [0.0] + merged + [duration]
    return {
        "cuts_s": cuts[:200],
        "n_cuts": len(cuts),
        "changes_s": merged[:300],
        "n_changes": len(merged),
        "first_change_s": merged[0] if merged else None,
        "changes_in_first_3s": sum(1 for c in merged if c <= 3.0),
        "changes_per_10s": round(len(merged) / duration * 10, 2) if duration else None,
        "avg_segment_s": round(duration / (len(merged) + 1), 2) if duration else None,
        "longest_segment_s": round(max(b - a for a, b in zip(edges, edges[1:])), 2) if duration else None,
        "note": ("cuts_s: hard scene cuts from the scene detector. changes_s: all abrupt visual changes "
                 "(cuts, jump cuts, graphics appearing), which is what pacing depends on."),
    }


# ----------------------------------------------------------------------------- motion
def lowres_frames(video, meta, limit_s, fps=5, width=64):
    import numpy as np
    h = max(2, int(round(width * meta["height"] / max(meta["width"], 1) / 2)) * 2)
    cmd = ["ffmpeg", "-v", "error", "-t", f"{limit_s:.3f}", "-i", str(video),
           "-vf", f"fps={fps},scale={width}:{h},format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    code, raw, _ = run(cmd, binary_out=True)
    n = len(raw) // (width * h)
    if code != 0 or n < 2:
        return None, fps
    frames = np.frombuffer(raw[: n * width * h], dtype=np.uint8).reshape(n, h, width).astype(np.float32) / 255.0
    return frames, fps


def runs_below(values, threshold, step, min_len):
    """Contiguous stretches where values stay under threshold for at least min_len seconds."""
    out, start = [], None
    for i, v in enumerate(list(values) + [threshold + 1]):
        if v < threshold and start is None:
            start = i
        elif v >= threshold and start is not None:
            if (i - start) * step >= min_len:
                out.append([round(start * step, 2), round(i * step, 2)])
            start = None
    return out


def motion_label(value):
    """Rough words for the motion numbers. The cut-offs are rules of thumb, not measurements of anything."""
    if value is None:
        return "unknown"
    return "static" if value < 0.003 else "low" if value < 0.02 else "moderate" if value < 0.06 else "high"


def motion_stats(frames, fps):
    import numpy as np
    step = 1.0 / fps
    diffs = np.abs(frames[1:] - frames[:-1]).mean(axis=(1, 2))
    luma = frames.mean(axis=(1, 2))

    def window(a, b):
        seg = diffs[int(a * fps): max(int(b * fps), int(a * fps) + 1)]
        return round(float(seg.mean()), 4) if len(seg) else None

    row_mean, row_std = frames.mean(axis=(0, 2)), frames.std(axis=(0, 2))
    col_mean, col_std = frames.mean(axis=(0, 1)), frames.std(axis=(0, 1))

    def bars(mean, std):
        dark = (mean < 0.04) & (std < 0.03)
        lead = 0
        while lead < len(dark) and dark[lead]:
            lead += 1
        tail = 0
        while tail < len(dark) - lead and dark[len(dark) - 1 - tail]:
            tail += 1
        return (lead + tail) / len(dark)

    return {
        "mean": round(float(diffs.mean()), 4),
        "first_1s": window(0, 1),
        "s1_to_3": window(1, 3),
        "first_1s_label": motion_label(window(0, 1)),
        "overall_label": motion_label(float(diffs.mean())),
        "frozen_segments_s": runs_below(diffs, 0.003, step, 2.0)[:8],
        "start_luma": round(float(luma[: max(1, int(0.4 * fps))].mean()), 3),
        "letterbox_fraction": round(float(bars(row_mean, row_std)), 3),
        "pillarbox_fraction": round(float(bars(col_mean, col_std)), 3),
        "loop_similarity": round(float(1.0 - np.abs(frames[0] - frames[-1]).mean()), 3),
        "scale_note": ("mean absolute pixel change between frames sampled at 5 fps, 0-1; labels: under 0.003 static, "
                       "under 0.02 low, under 0.06 moderate, else high (rules of thumb)"),
    }


# ----------------------------------------------------------------------------- audio
def audio_stats(video, limit_s):
    import numpy as np
    cmd = ["ffmpeg", "-v", "error", "-t", f"{limit_s:.3f}", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
           "-f", "s16le", "-"]
    code, raw, _ = run(cmd, binary_out=True)
    if code != 0 or len(raw) < 3200:
        return None
    samples = np.frombuffer(raw[: len(raw) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
    win = 800                                           # 50 ms at 16 kHz
    n = len(samples) // win
    rms = np.sqrt((samples[: n * win].reshape(n, win) ** 2).mean(axis=1))
    db = 20 * np.log10(rms + 1e-9)
    threshold = max(SILENCE_FLOOR_DB, float(np.percentile(db, 95)) - 35.0)
    active = db > threshold
    onset = None
    for i in range(len(active) - 1):
        if active[i] and active[i + 1]:
            onset = i * 0.05
            break

    def power_db(a, b):
        seg = samples[int(a * 16000): int(b * 16000)]
        return round(float(10 * np.log10((seg ** 2).mean() + 1e-12)), 1) if len(seg) else None

    half = 10                                           # 0.5 s of 50 ms windows
    curve = [round(float(db[i: i + half].mean()), 1) for i in range(0, len(db), half)][:240]
    gaps = [g for g in runs_below(db, threshold, 0.05, 1.0) if g[0] > 0.2][:8]
    return {
        "mean_dbfs": power_db(0, len(samples) / 16000),
        "peak_dbfs": round(float(20 * np.log10(np.abs(samples).max() + 1e-9)), 1),
        "first_1s_dbfs": power_db(0, 1),
        "sound_starts_s": None if onset is None else round(onset, 2),
        "silent_ratio": round(float(1.0 - active.mean()), 3),
        "silent_gaps_s": gaps,
        "loudness_curve_dbfs_per_0.5s": curve,
        "is_effectively_silent": bool(onset is None or float(np.percentile(db, 95)) < -45.0),
    }


# ----------------------------------------------------------------------------- transcript
def reachable(url, timeout=6):
    """True if the host answers at all. A proxy that refuses the connection counts as unreachable."""
    import urllib.error
    import urllib.request
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="HEAD"), timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def download(url, dest):
    """Fetch a file using the environment's proxy settings; curl is the fallback if Python's TLS setup differs."""
    import urllib.request
    tmp = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as fh:
            shutil.copyfileobj(resp, fh, 1 << 20)
    except Exception as first:
        if not have("curl"):
            raise
        code, _, err = run(["curl", "-fsSL", "--max-time", "900", "-o", str(tmp), url])
        if code != 0:
            raise RuntimeError(f"download failed ({str(first)[:80]}; curl: {err.strip()[:80]})")
    tmp.replace(dest)


def sherpa_files(model_name):
    """Whisper exported for sherpa-onnx plus a voice-activity model, cached after the first download."""
    import tarfile
    cache = Path(os.environ.get("VF_MODEL_DIR") or Path.home() / ".cache" / "virality-forecaster" / "models")
    cache.mkdir(parents=True, exist_ok=True)
    folder = cache / f"sherpa-onnx-whisper-{model_name}"
    files = [folder / f"{model_name}-encoder.int8.onnx", folder / f"{model_name}-decoder.int8.onnx",
             folder / f"{model_name}-tokens.txt"]
    if not all(f.exists() for f in files):
        archive = cache / f"sherpa-onnx-whisper-{model_name}.tar.bz2"
        download(f"{SHERPA_MODELS_URL}/sherpa-onnx-whisper-{model_name}.tar.bz2", archive)
        with tarfile.open(archive, "r:bz2") as tar:
            wanted = [m for m in tar.getmembers() if m.isfile() and m.name.endswith((".int8.onnx", "-tokens.txt"))
                      and not m.name.startswith(("/", "..")) and ".." not in Path(m.name).parts]
            try:
                tar.extractall(cache, members=wanted, filter="data")
            except TypeError:                           # Python without extraction filters
                tar.extractall(cache, members=wanted)
        archive.unlink()
        if not all(f.exists() for f in files):
            raise RuntimeError(f"the downloaded model '{model_name}' does not contain the expected files")
    vad = cache / "silero_vad.onnx"
    if not vad.exists():
        download(f"{SHERPA_MODELS_URL}/silero_vad.onnx", vad)
    return files, vad


def run_faster_whisper(wav, model_name, language):
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel(model_name, device="cpu", compute_type="int8", local_files_only=True)
    except Exception:
        if not reachable("https://huggingface.co"):
            raise RuntimeError("its model is not cached and huggingface.co is not reachable from here")
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
    seg_iter, info = model.transcribe(str(wav), language=language, word_timestamps=True, vad_filter=True)
    segments, words = [], []
    for seg in seg_iter:
        segments.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()})
        for w in (seg.words or []):
            words.append({"t": round(w.start, 2), "w": w.word.strip()})
    return segments, words, getattr(info, "language", language), "word-level"


def run_openai_whisper(wav, model_name, language):
    import whisper
    cached = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "whisper" / f"{model_name}.pt"
    if not cached.exists() and not reachable("https://openaipublic.azureedge.net"):
        raise RuntimeError("its model is not cached and its download host is not reachable from here")
    result = whisper.load_model(model_name).transcribe(str(wav), language=language, word_timestamps=True, fp16=False)
    segments, words = [], []
    for seg in result.get("segments", []):
        segments.append({"start": round(seg["start"], 2), "end": round(seg["end"], 2), "text": seg["text"].strip()})
        for w in seg.get("words", []) or []:
            words.append({"t": round(w["start"], 2), "w": w["word"].strip()})
    return segments, words, result.get("language", language), "word-level"


def run_sherpa_onnx(wav, model_name, language):
    """Voice detection finds the speech segments and their times; Whisper transcribes each one."""
    import wave

    import numpy as np
    import sherpa_onnx
    (encoder, decoder, tokens), vad_path = sherpa_files(model_name)
    with wave.open(str(wav)) as fh:
        samples = np.frombuffer(fh.readframes(fh.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = str(vad_path)
    cfg.silero_vad.min_silence_duration = 0.3
    cfg.silero_vad.min_speech_duration = 0.2
    cfg.silero_vad.max_speech_duration = 20.0            # Whisper reads at most 30 seconds at a time
    cfg.sample_rate = 16000
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)
    window = cfg.silero_vad.window_size
    spans = []

    def drain():
        while not vad.empty():
            spans.append((vad.front.start, np.array(vad.front.samples, dtype=np.float32)))
            vad.pop()

    for i in range(0, len(samples) - window + 1, window):
        vad.accept_waveform(samples[i:i + window])
        drain()
    vad.flush()
    drain()
    recognizer = sherpa_onnx.OfflineRecognizer.from_whisper(
        encoder=str(encoder), decoder=str(decoder), tokens=str(tokens), language=language or "",
        task="transcribe", num_threads=min(4, os.cpu_count() or 1))
    segments, words, langs = [], [], []
    for start, chunk in spans:
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, chunk)
        recognizer.decode_stream(stream)
        text = stream.result.text.strip()
        if not text:
            continue
        t0, t1 = start / 16000.0, (start + len(chunk)) / 16000.0
        segments.append({"start": round(t0, 2), "end": round(t1, 2), "text": text})
        langs.append(getattr(stream.result, "lang", "") or "")
        parts = text.split()
        total, done = sum(len(part) for part in parts) or 1, 0
        for part in parts:                               # no word timings from this engine: interpolate
            words.append({"t": round(t0 + (t1 - t0) * done / total, 2), "w": part})
            done += len(part)
    detected = max(set(langs), key=langs.count) if any(langs) else None
    return segments, words, language or detected, "segment-level (word times inside a segment are interpolated)"


RUNNERS = {"faster-whisper": run_faster_whisper, "openai-whisper": run_openai_whisper, "sherpa-onnx": run_sherpa_onnx}


def transcribe(video, limit_s, model_name, language):
    """Return (transcript dict or None, notes). Every installed engine is tried in turn until one works."""
    engines = [label for module, label in ENGINES if installed(module)]
    if not engines:
        return None, ["no speech-to-text engine installed (pip install sherpa-onnx or faster-whisper); spoken words "
                      "are unknown unless supplied with --transcript-file"]
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "audio.wav"
        code, _, err = run(["ffmpeg", "-v", "error", "-t", f"{limit_s:.3f}", "-i", str(video), "-vn", "-ac", "1",
                            "-ar", "16000", "-c:a", "pcm_s16le", "-y", str(wav)])
        if code != 0 or not wav.exists():
            return None, [f"could not extract audio for transcription: {err.strip()[:200]}"]
        for engine in engines:
            try:
                segments, words, lang, timing = RUNNERS[engine](wav, model_name, language)
                break
            except Exception as exc:                    # model download blocked, out of memory, ...
                failures.append(f"{engine}: {str(exc)[:140]}")
        else:
            hint = ("" if "sherpa-onnx" in engines else " If model downloads are blocked here, `pip install sherpa-onnx` "
                    "and run again: it fetches its model from GitHub.")
            return None, ["speech-to-text could not run (" + "; ".join(failures) + ")." + hint + " Otherwise get the "
                          "spoken words another way: ask for the script or the first line, read burned-in captions "
                          "off the frames, or pass --transcript-file"]
    notes = [f"{f}; used {engine} instead" for f in failures]
    text = " ".join(seg["text"] for seg in segments).strip()
    if not text:
        notes.append("no speech detected in the audio (music or ambient sound only)")
    speech_time = sum(seg["end"] - seg["start"] for seg in segments)
    return {
        "engine": engine,
        "model": model_name,
        "language": lang,
        "timing": timing,
        "text": text,
        "segments": segments,
        "first_word_s": words[0]["t"] if words else None,
        "words_first_3s": " ".join(w["w"] for w in words if w["t"] <= 3.0) if words else None,
        "n_words": len(words),
        "words_per_second_while_speaking": round(len(words) / speech_time, 2) if speech_time > 0 else None,
    }, notes


# ----------------------------------------------------------------------------- flags
def objective_flags(meta, pacing, motion, audio, transcript):
    """Checkable facts worth the judge's attention. They describe; the judge decides what they mean."""
    flags = []

    def add(flag_id, detail):
        flags.append({"id": flag_id, "detail": detail})

    if not meta["has_audio"] or (audio and audio["is_effectively_silent"]):
        add("no_audio", "no audible soundtrack; fine for sound-off feeds, a handicap where sound-on is the norm")
    elif audio and audio["sound_starts_s"] is not None and audio["sound_starts_s"] >= 0.5:
        add("dead_air_start", f"{audio['sound_starts_s']}s of silence before the first sound")
    if motion:
        if motion["start_luma"] < 0.06:
            add("black_start", "the first frames are near-black (fade-in or blank opener)")
        if (motion["first_1s"] or 0) < 0.003 and not any(c <= 1.0 for c in pacing["changes_s"]):
            add("static_start", "almost no visual change in the first second")
        if motion["frozen_segments_s"]:
            add("frozen_segments", f"still-image stretches of 2s or more at {motion['frozen_segments_s']}")
        if motion["letterbox_fraction"] >= 0.08 or motion["pillarbox_fraction"] >= 0.08:
            add("black_bars", f"black bars cover about {round(100 * max(motion['letterbox_fraction'], motion['pillarbox_fraction']))}% "
                              "of the frame (repurposed aspect ratio)")
    if pacing["first_change_s"] is None and meta["duration_s"] >= 8:
        add("single_shot", "no cut or abrupt visual change in the whole video")
    elif pacing["first_change_s"] and pacing["first_change_s"] >= 6:
        add("long_first_shot", f"the first cut or abrupt visual change arrives at {pacing['first_change_s']}s")
    if min(meta["width"], meta["height"]) < 540:
        add("low_resolution", f"{meta['width']}x{meta['height']}")
    if meta["orientation"] == "horizontal":
        add("horizontal", "landscape video; vertical feeds will show it small")
    if transcript and transcript.get("first_word_s") is not None and transcript["first_word_s"] >= 1.5:
        add("late_first_word", f"first spoken word at {transcript['first_word_s']}s")
    if audio and audio["silent_gaps_s"]:
        add("silent_gaps", f"silences of 1s or more at {audio['silent_gaps_s']}")
    return flags


# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Extract judgeable evidence from a short video.")
    ap.add_argument("video", nargs="?", help="path to the video file")
    ap.add_argument("--out", help="output directory (default: <video name>_analysis next to the video)")
    ap.add_argument("--check", action="store_true", help="report available dependencies and exit")
    ap.add_argument("--transcribe", choices=["auto", "off"], default="auto")
    ap.add_argument("--whisper-model", default="base",
                    help="whisper model size: tiny, base (default) or small; small is slower and better, "
                         "worth it for languages other than English")
    ap.add_argument("--language", default=None, help="spoken language code, e.g. en, ar, ro (default: detect)")
    ap.add_argument("--transcript-file", help="text file with the script/captions if you already have them")
    ap.add_argument("--timeline-frames", type=int, default=0, help="frames on the timeline sheet (default: auto 8-18)")
    ap.add_argument("--max-seconds", type=float, default=180.0, help="analyze at most this many seconds")
    args = ap.parse_args()

    env = check_environment()
    if args.check:
        print_environment(env)
        sys.exit(0 if env["ready"] else 1)
    if not args.video:
        ap.error("give a video path, or use --check")
    if not env["ready"]:
        print_environment(env)
        sys.exit(1)

    import numpy as np  # noqa: F401  (availability verified above)

    video = Path(args.video).expanduser()
    if not video.exists():
        sys.exit(f"File not found: {video}")
    out = Path(args.out).expanduser() if args.out else video.with_name(video.stem + "_analysis")
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    meta = probe(video)
    duration = meta["duration_s"]
    limit = min(duration, args.max_seconds) if duration > 0 else args.max_seconds
    notes = []
    if duration > args.max_seconds:
        notes.append(f"video is {duration:.0f}s; only the first {args.max_seconds:.0f}s were analyzed")
    meta["analyzed_seconds"] = round(limit, 2)
    last_t = max(0.0, limit - 0.12)

    # hook frames
    hook_frames, hook_labels = [], []
    for t in [t for t in HOOK_TIMES if t <= last_t] or [0.0]:
        path = frames_dir / f"hook_{t:05.2f}s.jpg"
        if extract_frame(video, t, path):
            hook_frames.append(path)
            hook_labels.append(f"{t:.2f}s")
    # timeline frames
    n_timeline = args.timeline_frames or int(min(18, max(8, round(limit / 2.5))))
    if limit < 4:
        n_timeline = max(3, int(limit * 2))
    times = [round(i * last_t / (n_timeline - 1), 2) for i in range(n_timeline)] if n_timeline > 1 else [0.0]
    tl_frames, tl_labels = [], []
    for t in times:
        path = frames_dir / f"t_{t:07.2f}s.jpg"
        if extract_frame(video, t, path):
            tl_frames.append(path)
            tl_labels.append(f"{t:.1f}s")
    if not hook_frames and not tl_frames:
        sys.exit("ffmpeg could not decode any frame from this file.")
    hook_sheet = contact_sheet(hook_frames, hook_labels, out / "hook_sheet.jpg")
    timeline_sheet = contact_sheet(tl_frames, tl_labels, out / "timeline_sheet.jpg")

    cuts = scene_cuts(video, limit)
    pacing = pacing_stats(cuts, abrupt_changes(video, meta, limit), limit)
    frames, fps = lowres_frames(video, meta, limit)
    motion = motion_stats(frames, fps) if frames is not None else None
    audio = audio_stats(video, limit) if meta["has_audio"] else None

    transcript = None
    if args.transcript_file:
        text = Path(args.transcript_file).expanduser().read_text(encoding="utf-8", errors="replace").strip()
        transcript = {"engine": "provided", "timing": "none", "text": text, "segments": [], "first_word_s": None,
                      "words_first_3s": None, "n_words": len(text.split()),
                      "words_per_second_while_speaking": None}
        notes.append("transcript was supplied by the user; word timings are unknown")
    elif args.transcribe == "auto" and meta["has_audio"] and not (audio and audio["is_effectively_silent"]):
        transcript, more = transcribe(video, limit, args.whisper_model, args.language)
        notes.extend(more)
    elif not meta["has_audio"]:
        notes.append("no audio stream")

    result = {
        "video": dict(meta, path=str(video)),
        "sheets": {
            "hook_sheet": str(hook_sheet) if hook_sheet else None,
            "timeline_sheet": str(timeline_sheet) if timeline_sheet else None,
            "frames_dir": str(frames_dir),
            "hook_times_s": [float(lbl[:-1]) for lbl in hook_labels],
            "timeline_times_s": [float(lbl[:-1]) for lbl in tl_labels],
        },
        "pacing": pacing,
        "motion": motion,
        "audio": audio,
        "transcript": transcript,
        "flags": objective_flags(meta, pacing, motion, audio, transcript),
        "notes": notes,
    }
    (out / "analysis.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    # compact human summary
    print(f"ANALYSIS  {video.name}")
    print(f"  {duration:.1f}s  {meta['width']}x{meta['height']} ({meta['orientation']})  {meta['fps']} fps  "
          f"audio: {'yes' if meta['has_audio'] else 'no'}")
    if pacing["n_changes"]:
        print(f"  pacing: {pacing['n_changes']} abrupt visual changes ({pacing['n_cuts']} of them hard scene cuts), "
              f"{pacing['changes_in_first_3s']} in the first 3s, first at {pacing['first_change_s']}s, "
              f"longest stretch without one {pacing['longest_segment_s']}s")
    else:
        print("  pacing: no cuts or abrupt visual changes detected")
    if motion:
        print(f"  motion: first 1s {motion['first_1s_label']} ({motion['first_1s']}), "
              f"1-3s {motion_label(motion['s1_to_3'])} ({motion['s1_to_3']}), overall {motion['overall_label']} "
              f"({motion['mean']}); last frame vs first frame similarity {motion['loop_similarity']}")
    if audio:
        print(f"  audio: sound starts at {audio['sound_starts_s']}s, mean {audio['mean_dbfs']} dBFS, "
              f"silent {round(100 * audio['silent_ratio'])}% of the time")
    if transcript and transcript["text"]:
        opener = transcript.get("words_first_3s") or transcript["text"][:120]
        about = "" if transcript.get("timing") == "word-level" else "about "
        print(f"  speech ({transcript['engine']}, language {transcript.get('language') or 'unknown'}): first word at "
              f"{about}{transcript.get('first_word_s')}s; first 3 seconds: \"{opener}\"")
    elif transcript:
        print("  speech: none detected")
    else:
        print("  speech: no transcript (see NOTE)")
    for flag in result["flags"]:
        print(f"  FLAG {flag['id']}: {flag['detail']}")
    for note in notes:
        print(f"  NOTE {note}")
    print("\nNow look at these images before judging:")
    for key in ("hook_sheet", "timeline_sheet"):
        if result["sheets"][key]:
            print(f"  {result['sheets'][key]}")
    print(f"  (single frames at higher resolution: {frames_dir})")
    print(f"Full data: {out / 'analysis.json'}")


if __name__ == "__main__":
    try:
        main()
        sys.stdout.flush()
    except BrokenPipeError:                             # output was piped into something like `head`
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
