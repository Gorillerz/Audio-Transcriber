"""Shared command-line helpers for local ASR feasibility runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np


def build_parser(description: str) -> argparse.ArgumentParser:
    """Create consistent input and excerpt options for each model runner."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("audio", type=Path, help="Source audio file; it is never modified.")
    parser.add_argument("--start", type=float, default=0, help="Excerpt start in seconds (default: 0).")
    parser.add_argument("--duration", type=float, default=60, help="Excerpt length in seconds (default: 60).")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "results")
    parser.add_argument("--device", choices=("auto", "gpu", "cpu"), default="auto")
    return parser


def prepare_excerpt(source: Path, start: float, duration: float) -> tuple[np.ndarray, int, float]:
    """Decode an audio excerpt to mono 16 kHz float32 without changing its source."""
    if not source.is_file():
        raise FileNotFoundError(source)
    if start < 0 or duration <= 0:
        raise ValueError("--start must be >= 0 and --duration must be > 0")

    # Keep the temporary decode in the prototype's ignored folder. This also
    # avoids Windows sandbox temp locations that external ffmpeg cannot write.
    temp_root = Path(__file__).parent / ".tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="journal-asr-", dir=temp_root) as temp_dir:
        wav_path = Path(temp_dir) / "excerpt.wav"
        command = [
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", str(start), "-i", str(source), "-t", str(duration),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode:
            raise RuntimeError(f"ffmpeg could not decode the excerpt: {completed.stderr.strip()}")
        with wave.open(str(wav_path), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getframerate() != 16000:
                raise RuntimeError("Excerpt conversion did not produce mono 16 kHz audio")
            frame_count = wav.getnframes()
            samples = np.frombuffer(wav.readframes(frame_count), dtype="<i2")
    return samples.astype(np.float32) / 32768.0, 16000, frame_count / 16000


def select_device(torch: Any, choice: str) -> str:
    """Choose CUDA-compatible PyTorch GPU (including ROCm) or CPU explicitly."""
    gpu_available = bool(torch.cuda.is_available())
    if choice == "gpu" and not gpu_available:
        raise RuntimeError("GPU was requested, but torch.cuda.is_available() is false")
    return "cuda:0" if choice == "gpu" or (choice == "auto" and gpu_available) else "cpu"


def runtime_info(torch: Any, device: str) -> dict[str, Any]:
    """Capture the runtime facts needed to compare runs and diagnose device use."""
    device_name = None
    if device.startswith("cuda"):
        device_name = torch.cuda.get_device_name(0)
    return {
        "python": os.sys.version.split()[0],
        "torch": torch.__version__,
        "torch_hip": getattr(torch.version, "hip", None),
        "torch_cuda": getattr(torch.version, "cuda", None),
        "device": device,
        "device_name": device_name,
    }


def jsonable(value: Any) -> Any:
    """Convert model-specific output objects into JSON-compatible data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if hasattr(value, "__dict__"):
        return jsonable(vars(value))
    return str(value)


def save_result(
    *, output_dir: Path, source: Path, start: float, duration: float,
    provider: str, model: str, runtime: dict[str, Any], load_seconds: float,
    inference_seconds: float, transcript: str, timestamps: Any,
    detected_language: str | None = None,
) -> Path:
    """Persist a private, reproducible run report and companion plain transcript."""
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with source.open("rb") as audio_file:
        for chunk in iter(lambda: audio_file.read(1024 * 1024), b""):
            digest.update(chunk)
    file_hash = digest.hexdigest()
    safe_name = "_".join(source.stem.split())[:60]
    stem = f"{safe_name}_{provider}_{int(time.time())}"
    result = {
        "provider": provider,
        "model": model,
        "source_file_name": source.name,
        "source_sha256": file_hash,
        "excerpt_start_seconds": start,
        "requested_excerpt_seconds": duration,
        "runtime": runtime,
        "model_load_seconds": round(load_seconds, 3),
        "inference_seconds": round(inference_seconds, 3),
        "real_time_factor": round(inference_seconds / duration, 4) if duration else None,
        "detected_language": detected_language,
        "transcript": transcript,
        "timestamps": jsonable(timestamps),
    }
    json_path = output_dir / f"{stem}.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    json_path.with_suffix(".txt").write_text(transcript.rstrip() + "\n", encoding="utf-8")
    return json_path
