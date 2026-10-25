"""Run word-timestamped OpenAI Whisper medium in the configured WSL environment."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def normalize_word_timestamps(segments: list[dict]) -> list[dict]:
    """Flatten Whisper segments while preserving word probability with timing and text."""
    words = []
    for segment in segments:
        for word in segment.get("words", []):
            probability = word.get("probability")
            words.append({
                "start": float(word["start"]),
                "end": float(word["end"]),
                "text": word["word"],
                "probability": float(probability) if probability is not None else None,
            })
    return words


def transcribe(audio_path: Path, output_path: Path, model_name: str) -> None:
    """Write a normalized transcript and word-level timestamps for the app API."""
    import torch
    import whisper

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = whisper.load_model(model_name, device=device)
    response = model.transcribe(str(audio_path), word_timestamps=True, verbose=False)
    segments = response.get("segments", [])
    words = normalize_word_timestamps(segments)
    output_path.write_text(json.dumps({
        "text": response.get("text", "").strip(),
        "language": response.get("language"),
        "segments": segments,
        "words": words,
        "provider": "OpenAI Whisper",
        "model": model_name,
        "device": torch.cuda.get_device_name(0) if device == "cuda" else "CPU",
    }, ensure_ascii=False), encoding="utf-8")


def main() -> None:
    """Validate command-line paths and execute one transcription request."""
    if len(sys.argv) != 4:
        raise SystemExit("usage: whisper_worker.py AUDIO_PATH OUTPUT_JSON MODEL_NAME")
    transcribe(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])


if __name__ == "__main__":
    main()
