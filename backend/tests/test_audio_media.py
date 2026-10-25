"""Tests for cached waveform extraction and playback renditions using synthetic WAV audio."""

from array import array
from io import BytesIO
from pathlib import Path
import subprocess
import wave

import app.audio_media as audio_media
from app.audio_media import AudioMediaService
from app.storage import Catalog


def _recording(catalog: Catalog) -> tuple[dict, bytes]:
    """Import a short synthetic WAV so media tests never depend on private journal audio."""
    buffer = BytesIO()
    with wave.open(buffer, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(8_000)
        target.writeframes(array("h", [0] * 400 + [16_384] * 400).tobytes())
    payload = buffer.getvalue()
    return catalog.import_file("synthetic.wav", BytesIO(payload), "audio/wav")[0], payload


def test_waveform_is_normalized_cached_and_uses_short_audio_chunks(tmp_path, monkeypatch):
    """Waveform extraction preserves peaks and reads the source only once per content hash."""
    catalog = Catalog(tmp_path / "library")
    recording, _ = _recording(catalog)
    pcm = array("h", [0] * 400 + [16_384] * 400).tobytes()
    calls = 0

    class FakeProcess:
        stdout = BytesIO(pcm)

        def wait(self):
            return 0

    def fake_popen(*args, **kwargs):
        nonlocal calls
        calls += 1
        return FakeProcess()

    monkeypatch.setattr(audio_media.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(AudioMediaService, "_ffmpeg", staticmethod(lambda: "ffmpeg-test"))
    service = AudioMediaService(catalog)

    first = service.waveform(recording)
    second = service.waveform(recording)

    assert first["sample_rate"] == 20
    assert first["peaks"] == [0.0, 0.5]
    assert second == first
    assert calls == 1


def test_browser_mp3_is_cached_and_source_file_is_unchanged(tmp_path, monkeypatch):
    """Fallback conversion writes a cached derivative without modifying original audio."""
    catalog = Catalog(tmp_path / "library")
    recording, original = _recording(catalog)
    calls = 0

    def fake_run(command, **kwargs):
        nonlocal calls
        calls += 1
        with open(command[-1], "wb") as output:
            output.write(b"synthetic mp3 rendition")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(audio_media.subprocess, "run", fake_run)
    monkeypatch.setattr(AudioMediaService, "_ffmpeg", staticmethod(lambda: "ffmpeg-test"))
    service = AudioMediaService(catalog)

    first = service.browser_playback_path(recording)
    second = service.browser_playback_path(recording)

    assert first == second
    assert first.read_bytes() == b"synthetic mp3 rendition"
    assert calls == 1
    assert Path(recording["stored_path"]).read_bytes() == original
    service.discard(recording)
    assert not first.exists()
    assert Path(recording["stored_path"]).read_bytes() == original
