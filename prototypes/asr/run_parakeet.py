"""Run Parakeet TDT 0.6B v3 locally and save transcript plus token timings."""

from __future__ import annotations

import time

import torch
from transformers import AutoModelForTDT, AutoProcessor

from common import build_parser, prepare_excerpt, runtime_info, save_result, select_device


def main() -> None:
    """Load Parakeet, transcribe one excerpt, and persist timing/performance details."""
    args = build_parser("Prototype Parakeet TDT 0.6B v3 on a local audio excerpt.").parse_args()
    device = select_device(torch, args.device)
    precision = torch.float16 if device.startswith("cuda") else torch.float32

    started = time.perf_counter()
    processor = AutoProcessor.from_pretrained("nvidia/parakeet-tdt-0.6b-v3")
    model = AutoModelForTDT.from_pretrained(
        "nvidia/parakeet-tdt-0.6b-v3",
        dtype=precision,
        device_map=device,
    )
    load_seconds = time.perf_counter() - started

    audio, sample_rate, actual_duration = prepare_excerpt(args.audio, args.start, args.duration)
    inputs = processor(audio, sampling_rate=sample_rate, return_tensors="pt", return_attention_mask=True)
    inputs.to(model.device, dtype=model.dtype)
    if device.startswith("cuda"):
        torch.cuda.synchronize()
    started = time.perf_counter()
    with torch.inference_mode():
        generated = model.generate(**inputs, return_dict_in_generate=True)
    if device.startswith("cuda"):
        torch.cuda.synchronize()
    inference_seconds = time.perf_counter() - started
    decoded, timestamps = processor.decode(
        generated.sequences,
        durations=generated.durations,
        skip_special_tokens=True,
    )
    transcript = decoded[0] if isinstance(decoded, list) else str(decoded)
    token_times = timestamps[0] if timestamps else []
    result_path = save_result(
        output_dir=args.output_dir,
        source=args.audio,
        start=args.start,
        duration=actual_duration,
        provider="parakeet",
        model="nvidia/parakeet-tdt-0.6b-v3",
        runtime=runtime_info(torch, device),
        load_seconds=load_seconds,
        inference_seconds=inference_seconds,
        transcript=transcript,
        timestamps=token_times,
    )
    print(f"Transcript: {transcript}")
    print(f"Timed tokens: {len(token_times)}")
    print(f"Inference: {inference_seconds:.2f}s; result: {result_path}")


if __name__ == "__main__":
    main()
