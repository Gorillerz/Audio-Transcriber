"""Create cached playback-compatible audio and waveform data without changing source recordings."""

from __future__ import annotations

from array import array
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .storage import Catalog

WAVEFORM_RATE = 20
PCM_RATE = 8_000
SAMPLES_PER_PEAK = PCM_RATE // WAVEFORM_RATE


class AudioMediaService:
    """Generate reusable browser playback files and compact waveform envelopes per library."""

    def __init__(self, catalog: Catalog) -> None:
        """Keep derived media beside the library database, separate from source audio."""
        self.catalog = catalog
        self.waveform_dir = catalog.root / "Cache" / "Waveforms"
        self.playback_dir = catalog.root / "Cache" / "Playback"

    def waveform(self, recording: dict) -> dict:
        """Return a 20 Hz normalized amplitude envelope, decoding audio in bounded PCM chunks."""
        digest = recording["sha256"]
        cache_path = self.waveform_dir / f"{digest}.json"
        if cache_path.is_file():
            return json.loads(cache_path.read_text(encoding="utf-8"))

        source = self._source_path(recording)
        try:
            process = subprocess.Popen(
                [self._ffmpeg(), "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", str(PCM_RATE), "-f", "s16le", "-"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise RuntimeError(f"FFmpeg could not be started: {error}") from error
        peaks: list[float] = []
        try:
            assert process.stdout is not None
            while True:
                raw = process.stdout.read(SAMPLES_PER_PEAK * 2)
                if not raw:
                    break
                if len(raw) % 2:
                    raw = raw[:-1]
                samples = array("h")
                samples.frombytes(raw)
                if os.sys.byteorder != "little":
                    samples.byteswap()
                peaks.append(max((abs(value) for value in samples), default=0) / 32768)
            return_code = process.wait()
        finally:
            if process.stdout:
                process.stdout.close()
        if return_code:
            raise RuntimeError("FFmpeg could not decode this recording to build its waveform.")
        result = {"recording_id": recording["id"], "duration_seconds": recording.get("duration_seconds"), "sample_rate": WAVEFORM_RATE, "peaks": peaks}
        self._write_json(cache_path, result)
        return result

    def browser_playback_path(self, recording: dict) -> Path:
        """Return a cached MP3 rendition for browsers that cannot play the source format."""
        source = self._source_path(recording)
        destination = self.playback_dir / f"{recording['sha256']}.mp3"
        if destination.is_file():
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix="playback-", suffix=".mp3", dir=destination.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
            try:
                completed = subprocess.run(
                    [self._ffmpeg(), "-v", "error", "-y", "-i", str(source), "-vn", "-codec:a", "libmp3lame", "-q:a", "3", str(temporary_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except OSError as error:
                raise RuntimeError(f"FFmpeg could not be started: {error}") from error
            if completed.returncode:
                raise RuntimeError(completed.stderr.strip() or "FFmpeg could not convert this recording for browser playback.")
            os.replace(temporary_path, destination)
            return destination
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)

    def discard(self, recording: dict) -> None:
        """Remove disposable media derivatives after their catalog recording is removed."""
        digest = recording["sha256"]
        for cache_path in (self.waveform_dir / f"{digest}.json", self.playback_dir / f"{digest}.mp3"):
            try:
                cache_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _source_path(self, recording: dict) -> Path:
        """Validate the catalog path before passing it to FFmpeg."""
        source = Path(recording["stored_path"])
        if not source.is_file():
            raise FileNotFoundError("Audio file is missing from the library")
        return source

    @staticmethod
    def _ffmpeg() -> str:
        """Resolve an optional explicit FFmpeg path before searching the system PATH."""
        configured = os.environ.get("JOURNAL_FFMPEG_PATH")
        executable = configured or shutil.which("ffmpeg")
        if not executable:
            raise RuntimeError("FFmpeg is required to prepare this audio. Install FFmpeg or set JOURNAL_FFMPEG_PATH.")
        return executable

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
        """Atomically save a reusable waveform cache to avoid partial reads."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix="waveform-", suffix=".tmp", dir=path.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(payload, temporary, separators=(",", ":"))
            os.replace(temporary_path, path)
        finally:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)
