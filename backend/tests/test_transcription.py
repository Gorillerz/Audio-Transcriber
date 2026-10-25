"""Focused tests for local transcription estimates and persistent run state."""

import json
import shlex
import subprocess
from io import BytesIO

from app.storage import Catalog
from app.transcription import LocalWhisper, estimated_seconds
from app.whisper_worker import normalize_word_timestamps


def test_whisper_estimate_uses_the_measured_sixty_second_rate():
    """The estimate scales from the measured minute and includes warm startup overhead."""
    assert estimated_seconds(60) == 32
    assert estimated_seconds(2700) == 887


def test_worker_normalizes_word_timing_and_probability():
    """Whisper's word score survives normalization alongside text and timestamps."""
    words = normalize_word_timestamps([{"words": [
        {"start": 0.1, "end": 0.4, "word": " Bonjour", "probability": 0.73},
        {"start": 0.4, "end": 0.8, "word": "!"},
    ]}])

    assert words == [
        {"start": 0.1, "end": 0.4, "text": " Bonjour", "probability": 0.73},
        {"start": 0.4, "end": 0.8, "text": "!", "probability": None},
    ]


def test_provider_probe_reports_the_detected_gpu_and_estimate(tmp_path, monkeypatch):
    """The UI gets actual WSL device information rather than a hard-coded GPU claim."""
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(
            args=command, returncode=0, stdout=json.dumps({"available": True, "gpu": "AMD Radeon RX 9060 XT"}), stderr=""
        )

    monkeypatch.setattr(
        "app.transcription.subprocess.run",
        fake_run,
    )
    provider = LocalWhisper(Catalog(tmp_path / "library")).provider_info(60)

    assert provider["available"] is True
    assert provider["gpu_name"] == "AMD Radeon RX 9060 XT"
    assert provider["estimated_seconds"] == 32
    assert provider["timing"] == "Word-level timestamps"
    assert "dict(available=bool" in commands[0][-1]
    assert "'available'" not in commands[0][-1]


def test_transcription_run_result_persists_in_library_database(tmp_path):
    """Run status and provider output remain available after reopening the local catalog."""
    library = tmp_path / "library"
    catalog = Catalog(library)
    recording, _, _ = catalog.import_file("journal.wav", BytesIO(b"fixture"), "audio/wav")
    run = catalog.create_transcription_run(recording["id"], "wsl-whisper", "openai/whisper-medium", "AMD Radeon RX 9060 XT")
    result = {"text": "A raw transcript", "words": [{"start": 0.1, "end": 0.4, "text": "A"}]}

    catalog.finish_transcription_run(run["id"], "succeeded", result=result)
    restored = Catalog(library).get_transcription_run(run["id"])

    assert restored["status"] == "succeeded"
    assert restored["result"] == result
    assert restored["elapsed_seconds"] >= 0


def test_catalog_reopen_marks_interrupted_run_failed(tmp_path):
    """A service restart gives an active run a clear retryable outcome instead of spinning forever."""
    library = tmp_path / "library"
    catalog = Catalog(library)
    recording, _, _ = catalog.import_file("journal.wav", BytesIO(b"fixture"), "audio/wav")
    run = catalog.create_transcription_run(recording["id"], "wsl-whisper", "openai/whisper-medium", "AMD Radeon RX 9060 XT")

    restored = Catalog(library).get_transcription_run(run["id"])

    assert restored["status"] == "failed"
    assert "API restarted" in restored["error"]


def test_worker_command_quotes_wsl_paths_with_spaces(tmp_path):
    """Audio, result, and worker paths stay single shell arguments when the project path has spaces."""
    runner = LocalWhisper(Catalog(tmp_path / "library"))
    project = tmp_path / "Transcriber v2"
    paths = [
        project / "backend" / "app" / "whisper_worker.py",
        project / "audio files" / "journal.wav",
        project / "temporary results" / "run.json",
    ]

    command = runner._worker_command(*paths)

    assert command[:6] == ["wsl.exe", "-d", "Ubuntu-24.04", "--", "bash", "-lc"]
    assert all(shlex.quote(LocalWhisper._wsl_path(path)) in command[-1] for path in paths)
    assert '"$HOME"/.venvs/rocm-asr-probe/bin/python' in command[-1]
    assert '"$@"' not in command[-1]

