"""Local WSL Whisper adapter and background-run orchestration for MVP3."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PureWindowsPath

from .asr_catalog import DEFAULT_TRANSCRIPTION_MODEL_ID, TRANSCRIPTION_MODELS, list_transcription_models
from .storage import Catalog
from .workflows import WorkflowStore

PROVIDER_ID = "wsl-whisper"
MODEL_ID = DEFAULT_TRANSCRIPTION_MODEL_ID
BENCHMARK_RTF = 19.45 / 60
BENCHMARK_STARTUP_SECONDS = 12.1


class LocalWhisper:
    """Probe the configured WSL GPU and run one Whisper job at a time."""

    def __init__(self, catalog: Catalog) -> None:
        """Use configurable WSL defaults so machine-specific paths stay out of source."""
        self.catalog = catalog
        self.distro = os.environ.get("JOURNAL_WSL_DISTRO", "Ubuntu-24.04")
        self.python = os.environ.get("JOURNAL_WSL_PYTHON", "$HOME/.venvs/rocm-asr-probe/bin/python")
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="local-asr")
        self.lock = threading.Lock()
        self._probe_lock = threading.Lock()
        self._probe_cache: tuple[float, dict] | None = None

    def provider_info(self, duration_seconds: float | None, model_id: str = MODEL_ID) -> dict:
        """Report current GPU availability and a benchmark-based warm-run estimate."""
        model = TRANSCRIPTION_MODELS.get(model_id)
        if not model:
            return self._unavailable(f"Unsupported local transcription model: {model_id}", {"id": model_id, "name": model_id})
        with self._probe_lock:
            if self._probe_cache and time.monotonic() - self._probe_cache[0] < 30:
                details = self._probe_cache[1]
            else:
                code = "import json,torch,whisper; print(json.dumps(dict(available=bool(torch.cuda.is_available()), gpu=torch.cuda.get_device_name(0) if torch.cuda.is_available() else None)))"
                command = ["wsl.exe", "-d", self.distro, "--", "bash", "-lc", f'exec "{self.python}" -c {shlex.quote(code)}']
                try:
                    completed = subprocess.run(command, capture_output=True, text=True, timeout=18, check=False)
                    if completed.returncode != 0:
                        return self._unavailable(completed.stderr.strip() or "WSL Whisper environment could not be started.")
                    details = json.loads(completed.stdout.strip().splitlines()[-1])
                    self._probe_cache = (time.monotonic(), details)
                except (OSError, subprocess.SubprocessError, json.JSONDecodeError, IndexError) as error:
                    return self._unavailable(str(error) or "Could not check the local WSL GPU.")
        estimate = round(max(0.0, duration_seconds) * BENCHMARK_RTF + BENCHMARK_STARTUP_SECONDS) if duration_seconds is not None else None
        return {
            "id": PROVIDER_ID,
            "name": f"Local GPU · {model['name']}",
            "provider": model["provider"],
            "model": model_id,
            "available": details["available"],
            "gpu_name": details["gpu"],
            "timing": model["timing"],
            "languages": model["languages"],
            "estimated_seconds": estimate,
            "estimate_note": "Approximate warm-run estimate from the 60-second benchmark; the first model download or cold start may take longer.",
            "reason": None if details["available"] else "WSL is available, but PyTorch cannot access a GPU.",
        }

    @staticmethod
    def _unavailable(reason: str, model: dict | None = None) -> dict:
        """Return a stable provider shape even when WSL or its model environment is missing."""
        model = model or TRANSCRIPTION_MODELS[MODEL_ID]
        return {
            "id": PROVIDER_ID,
            "name": f"Local GPU · {model['name']}",
            "provider": model.get("provider", "Local WSL model"),
            "model": model["id"],
            "available": False,
            "gpu_name": None,
            "timing": model.get("timing", "Provider timing capability unavailable"),
            "languages": model.get("languages", "Provider language support unavailable"),
            "estimated_seconds": None,
            "estimate_note": "Approximate warm-run estimate from the 60-second benchmark; the first model download or cold start may take longer.",
            "reason": reason,
        }

    @staticmethod
    def _wsl_path(path: Path) -> str:
        """Map a Windows drive path to WSL's standard /mnt/<drive> mount."""
        windows = PureWindowsPath(path.resolve())
        if not windows.drive:
            raise ValueError("The WSL transcription runner requires files on a Windows drive.")
        return "/mnt/" + windows.drive[0].lower() + "/" + "/".join(windows.parts[1:])

    def _worker_command(self, worker_path: Path, audio_path: Path, result_path: Path, engine_model: str = "medium") -> list[str]:
        """Build one shell-quoted WSL invocation so spaces cannot split any file path."""
        if self.python.startswith("$HOME/"):
            python = '"$HOME"/' + shlex.quote(self.python[len("$HOME/"):])
        else:
            python = shlex.quote(self.python)
        arguments = [self._wsl_path(path) for path in (worker_path, audio_path, result_path)]
        arguments.append(engine_model)
        command_text = "exec " + python + " " + " ".join(shlex.quote(argument) for argument in arguments)
        return ["wsl.exe", "-d", self.distro, "--", "bash", "-lc", command_text]

    def start(self, recording_id: str, model_id: str = MODEL_ID) -> dict:
        """Persist and queue a local transcription run after validating provider readiness."""
        model = TRANSCRIPTION_MODELS.get(model_id)
        if not model:
            raise ValueError(f"Unsupported local transcription model: {model_id}")
        recording = self.catalog.get_recording(recording_id)
        if not recording:
            raise KeyError("Recording not found.")
        info = self.provider_info(recording.get("duration_seconds"), model_id)
        if not info["available"]:
            raise RuntimeError(info["reason"] or "Local GPU transcription is unavailable.")
        if not recording.get("duration_seconds"):
            raise ValueError("The recording duration is unavailable, so an execution estimate cannot be calculated.")
        with self.lock:
            active = self.catalog.active_transcription_run()
            if active:
                raise RuntimeError("Another local transcription is already running.")
            run = self.catalog.create_transcription_run(recording_id, PROVIDER_ID, model_id, info["gpu_name"])
            if not run:
                raise KeyError("Recording not found.")
            self.executor.submit(self._run, run["id"], Path(recording["stored_path"]), model["engine_model"])
        return {**run, "estimated_seconds": info["estimated_seconds"], "gpu_name": info["gpu_name"]}

    def transcribe_for_pipeline(self, recording_id: str, model_id: str) -> dict:
        """Run local ASR synchronously for a pipeline stage while preserving a transcription run."""
        model = TRANSCRIPTION_MODELS.get(model_id)
        if not model:
            raise ValueError(f"Unsupported local transcription model: {model_id}")
        recording = self.catalog.get_recording(recording_id)
        if not recording:
            raise KeyError("Recording not found.")
        info = self.provider_info(recording.get("duration_seconds"), model_id)
        if not info["available"]:
            raise RuntimeError(info["reason"] or "Local GPU transcription is unavailable.")
        with self.lock:
            active = self.catalog.active_transcription_run()
            if active:
                raise RuntimeError("Another local transcription is already running.")
            run = self.catalog.create_transcription_run(recording_id, PROVIDER_ID, model_id, info["gpu_name"])
            if not run:
                raise KeyError("Recording not found.")
        try:
            result = self._transcribe(Path(recording["stored_path"]), model["engine_model"])
            return self._save_result(run["id"], result)
        except Exception as error:
            self.catalog.finish_transcription_run(run["id"], "failed", error=str(error))
            raise

    def _transcribe(self, audio_path: Path, engine_model: str) -> dict:
        """Invoke the WSL worker for one audio file and return its structured result."""
        result_path: Path | None = None
        try:
            handle = tempfile.NamedTemporaryFile(prefix="journal-asr-", suffix=".json", delete=False)
            result_path = Path(handle.name)
            handle.close()
            worker_path = Path(__file__).with_name("whisper_worker.py")
            command = self._worker_command(worker_path, audio_path, result_path, engine_model)
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                raise RuntimeError((completed.stderr.strip() or completed.stdout.strip() or "Whisper worker failed.")[-2000:])
            return json.loads(result_path.read_text(encoding="utf-8"))
        finally:
            if result_path:
                result_path.unlink(missing_ok=True)

    def _save_result(self, run_id: str, result: dict) -> dict:
        """Append raw text, publish the official transcription, and retain provider timings."""
        recording_id = self.catalog.get_transcription_recording_id(run_id)
        run = self.catalog.get_transcription_run(run_id) or {}
        saved = WorkflowStore(self.catalog.db_path).save_raw_transcript(
            recording_id, result.get("text", ""), provider=run.get("provider", PROVIDER_ID), model=run.get("model", MODEL_ID),
        )
        result["transcript_id"] = saved["id"]
        result["transcript_version"] = saved["version"]
        result["official_output_id"] = saved["official_output_id"]
        self.catalog.finish_transcription_run(run_id, "succeeded", result=result)
        return result

    def _run(self, run_id: str, audio_path: Path, engine_model: str) -> None:
        """Run the WSL worker, preserve its word timings, and append the raw transcript."""
        try:
            self._save_result(run_id, self._transcribe(audio_path, engine_model))
        except Exception as error:
            self.catalog.finish_transcription_run(run_id, "failed", error=str(error))


def estimated_seconds(duration_seconds: float) -> int:
    """Calculate the warm Whisper estimate from the measured 60-second real-time factor."""
    return round(max(0.0, duration_seconds) * BENCHMARK_RTF + BENCHMARK_STARTUP_SECONDS)
