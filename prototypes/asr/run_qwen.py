"""Run Qwen3-ASR 1.7B with its forced aligner on a local audio excerpt."""

from __future__ import annotations

import time
import gc

import torch
from qwen_asr import Qwen3ASRModel, Qwen3ForcedAligner

from common import build_parser, prepare_excerpt, runtime_info, save_result, select_device


def main() -> None:
    """Load Qwen ASR and aligner, then save transcript and returned word timings."""
    args = build_parser("Prototype Qwen3-ASR 1.7B with forced alignment on a local excerpt.").parse_args()
    device = select_device(torch, args.device)
    # Half precision keeps the ASR model small enough for this machine's limited
    # free RAM; it is also the normal inference precision for the local GPU path.
    precision = torch.float16

    started = time.perf_counter()
    model = Qwen3ASRModel.from_pretrained(
        "Qwen/Qwen3-ASR-1.7B",
        dtype=precision,
        device_map=device,
        max_inference_batch_size=1,
        max_new_tokens=2048,
    )
    asr_load_seconds = time.perf_counter() - started

    # Qwen accepts a local audio path directly; decoding an excerpt to WAV also
    # normalizes sample rate/channels and keeps the original recording untouched.
    audio, sample_rate, actual_duration = prepare_excerpt(args.audio, args.start, args.duration)
    started = time.perf_counter()
    result = model.transcribe(
        audio=(audio, sample_rate),
        language=None,
        return_time_stamps=False,
    )[0]
    if device.startswith("cuda"):
        torch.cuda.synchronize()
    asr_seconds = time.perf_counter() - started
    transcript = getattr(result, "text", "")
    language = getattr(result, "language", None)

    # Load the aligner after freeing ASR weights so the prototype does not need
    # both large models resident in memory at the same time.
    del model
    gc.collect()
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    started = time.perf_counter()
    aligner = Qwen3ForcedAligner.from_pretrained(
        "Qwen/Qwen3-ForcedAligner-0.6B",
        dtype=precision,
        device_map=device,
    )
    aligner_load_seconds = time.perf_counter() - started
    started = time.perf_counter()
    aligned = aligner.align(
        audio=(audio, sample_rate),
        text=transcript,
        language=language or "English",
    )
    if device.startswith("cuda"):
        torch.cuda.synchronize()
    align_seconds = time.perf_counter() - started
    # The aligner wraps timed word records in a result object; save the records
    # themselves so they match the app's flat segment/word representation.
    timestamps = getattr(aligned[0], "items", aligned[0]) if aligned else []
    load_seconds = asr_load_seconds + aligner_load_seconds
    inference_seconds = asr_seconds + align_seconds
    result_path = save_result(
        output_dir=args.output_dir,
        source=args.audio,
        start=args.start,
        duration=actual_duration,
        provider="qwen",
        model="Qwen/Qwen3-ASR-1.7B + Qwen/Qwen3-ForcedAligner-0.6B",
        runtime=runtime_info(torch, device),
        load_seconds=load_seconds,
        inference_seconds=inference_seconds,
        transcript=transcript,
        timestamps=timestamps,
        detected_language=language,
    )
    print(f"Detected language: {language}")
    print(f"Transcript: {transcript}")
    print(f"Timestamps: {len(timestamps or [])}")
    print(f"Inference: {inference_seconds:.2f}s; result: {result_path}")


if __name__ == "__main__":
    main()
