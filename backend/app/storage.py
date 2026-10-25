"""SQLite catalog and managed audio-file storage for MVP1."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from mutagen import File as MutagenFile
from mutagen.mp3 import MP3
from send2trash import send2trash

SUPPORTED_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus", ".aac", ".wma", ".webm", ".mp4"}
PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIBRARY_ROOT_CONFIG = PROJECT_ROOT / ".journal-library-root"


def default_library_root() -> Path:
    """Load the pinned project library before environment and platform defaults."""
    if LIBRARY_ROOT_CONFIG.is_file():
        configured = LIBRARY_ROOT_CONFIG.read_text(encoding="utf-8").strip()
        if not configured:
            raise RuntimeError(f"The library path file is empty: {LIBRARY_ROOT_CONFIG}")
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path = path.resolve()
        if not (path / "app.sqlite").is_file() or not (path / "Audio").is_dir():
            raise RuntimeError(
                f"The configured library is missing or incomplete: {path}. "
                f"Restore that folder or correct {LIBRARY_ROOT_CONFIG.name}; the app will not open a new empty library."
            )
        return path
    explicit = os.environ.get("JOURNAL_LIBRARY_DIR")
    if explicit:
        return Path(explicit).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "JournalTranscriber" / "Library"


class Catalog:
    """Own the SQLite catalog and audio files in the configured library folder."""

    def __init__(self, library_root: Path | None = None) -> None:
        """Create library folders and initialize the catalog schema if needed."""
        self.root = (library_root or default_library_root()).resolve()
        self.audio_dir = self.root / "Audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "app.sqlite"
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        """Open a row-aware SQLite connection with foreign-key checks enabled."""
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        """Create recording and confirmed-file-alias tables on first launch."""
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS recordings (
                    id TEXT PRIMARY KEY,
                    original_name TEXT NOT NULL,
                    stored_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL UNIQUE,
                    size_bytes INTEGER NOT NULL,
                    duration_seconds REAL,
                    media_date TEXT,
                    imported_at TEXT NOT NULL,
                    mime_type TEXT,
                    extension TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'untranscribed',
                    status_source TEXT NOT NULL DEFAULT 'derived',
                    possible_match_id TEXT REFERENCES recordings(id)
                );
                CREATE TABLE IF NOT EXISTS file_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
                    original_name TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    added_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recording_groups (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS group_recordings (
                    group_id TEXT NOT NULL REFERENCES recording_groups(id) ON DELETE CASCADE,
                    recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
                    PRIMARY KEY(group_id, recording_id)
                );
                CREATE TABLE IF NOT EXISTS transcription_runs (
                    id TEXT PRIMARY KEY,
                    recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    device TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    error TEXT,
                    result_json TEXT
                );
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(recordings)")}
            if "status_source" not in columns:
                connection.execute("ALTER TABLE recordings ADD COLUMN status_source TEXT NOT NULL DEFAULT 'derived'")
            connection.execute(
                "UPDATE transcription_runs SET status='failed', finished_at=?, error=? WHERE status='running'",
                (datetime.now(timezone.utc).isoformat(), "Interrupted when the local API restarted; retry this transcription."),
            )
        self._repair_missing_audio_paths()
        self._backfill_missing_durations()

    def _repair_missing_audio_paths(self) -> None:
        """Repoint stale catalog paths only when a file in the managed ID folder matches its saved hash."""
        with self._connect() as connection:
            rows = connection.execute("SELECT id, original_name, stored_path, sha256 FROM recordings").fetchall()
            for row in rows:
                if Path(row["stored_path"]).is_file():
                    continue
                recording_dir = self.audio_dir / row["id"]
                if not recording_dir.is_dir():
                    continue
                preferred_names = [Path(row["original_name"]).name, Path(row["stored_path"]).name]
                candidates = [recording_dir / name for name in dict.fromkeys(preferred_names)]
                try:
                    candidates.extend(path for path in recording_dir.iterdir() if path.is_file() and path not in candidates)
                except OSError:
                    continue
                for candidate in candidates:
                    if not candidate.is_file() or self._file_sha256(candidate) != row["sha256"]:
                        continue
                    connection.execute("UPDATE recordings SET stored_path=? WHERE id=?", (str(candidate.resolve()), row["id"]))
                    break

    @staticmethod
    def _file_sha256(path: Path) -> str | None:
        """Hash a candidate in chunks so path repair verifies identity without loading audio into memory."""
        digest = hashlib.sha256()
        try:
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
        except OSError:
            return None
        return digest.hexdigest()

    def create_transcription_run(self, recording_id: str, provider: str, model: str, device: str) -> dict | None:
        """Persist a queued local-ASR run before its worker starts."""
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            if not connection.execute("SELECT 1 FROM recordings WHERE id=?", (recording_id,)).fetchone():
                return None
            connection.execute(
                "INSERT INTO transcription_runs(id,recording_id,provider,model,device,status,started_at) VALUES(?,?,?,?,?,?,?)",
                (run_id, recording_id, provider, model, device, "running", started_at),
            )
        return self.get_transcription_run(run_id)

    def get_transcription_run(self, run_id: str) -> dict | None:
        """Return a saved transcription run with its latest state and result."""
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM transcription_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["result"] = json.loads(result.pop("result_json")) if result.get("result_json") else None
        ended_at = datetime.fromisoformat(result["finished_at"]) if result["finished_at"] else datetime.now(timezone.utc)
        result["elapsed_seconds"] = max(0.0, (ended_at - datetime.fromisoformat(result["started_at"])).total_seconds())
        return result

    def active_transcription_run(self) -> dict | None:
        """Return the current local transcription so a second GPU job is not started."""
        with self._connect() as connection:
            row = connection.execute("SELECT id FROM transcription_runs WHERE status='running' ORDER BY started_at LIMIT 1").fetchone()
        return self.get_transcription_run(row["id"]) if row else None

    def latest_transcription_run(self, recording_id: str) -> dict | None:
        """Find the newest saved ASR result or active run for a recording."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id FROM transcription_runs WHERE recording_id=? ORDER BY started_at DESC LIMIT 1",
                (recording_id,),
            ).fetchone()
        return self.get_transcription_run(row["id"]) if row else None

    def get_transcription_recording_id(self, run_id: str) -> str:
        """Resolve the recording attached to a run before persisting its transcript."""
        with self._connect() as connection:
            row = connection.execute("SELECT recording_id FROM transcription_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise KeyError("Transcription run not found.")
        return row["recording_id"]

    def finish_transcription_run(self, run_id: str, status: str, result: dict | None = None, error: str | None = None) -> dict | None:
        """Finalize a transcription run while retaining provider output for review."""
        if status not in {"succeeded", "failed"}:
            raise ValueError("A finished transcription run must succeed or fail.")
        with self._connect() as connection:
            connection.execute(
                "UPDATE transcription_runs SET status=?,finished_at=?,error=?,result_json=? WHERE id=?",
                (status, datetime.now(timezone.utc).isoformat(), error, json.dumps(result) if result else None, run_id),
            )
        return self.get_transcription_run(run_id)

    def _backfill_missing_durations(self) -> None:
        """Recover durations for previously imported recordings whose metadata was unavailable."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, stored_path, media_date FROM recordings WHERE duration_seconds IS NULL"
            ).fetchall()
            for row in rows:
                path = Path(row["stored_path"])
                if not path.is_file():
                    continue
                duration, embedded_date = self._media_metadata(path)
                if duration is not None or (embedded_date and not row["media_date"]):
                    connection.execute(
                        "UPDATE recordings SET duration_seconds=COALESCE(?, duration_seconds), "
                        "media_date=COALESCE(media_date, ?) WHERE id=?",
                        (duration, embedded_date, row["id"]),
                    )

    @staticmethod
    def _media_metadata(path: Path) -> tuple[float | None, str | None]:
        """Read duration and embedded date when Mutagen recognizes the audio."""
        try:
            media = MutagenFile(path)
            duration = float(media.info.length) if media and getattr(media, "info", None) else None
            # Generic detection can return only an ID3 tag object for some MP3 files.
            if duration is None and path.suffix.lower() == ".mp3":
                duration = float(MP3(path).info.length)
            tags = media.tags if media else None
            date = None
            if tags:
                for key in ("date", "year", "TDRC", "©day"):
                    value = tags.get(key)
                    if value:
                        date = str(value[0] if isinstance(value, list) else value)[:32]
                        break
            if duration is None and path.suffix.lower() == ".wav":
                with wave.open(str(path), "rb") as wav_file:
                    duration = wav_file.getnframes() / wav_file.getframerate()
            return duration, date
        except Exception:
            return None, None

    def list_recordings(self) -> list[dict]:
        """Return catalog rows in newest-imported-first order."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT r.*, (SELECT COUNT(*) FROM file_aliases a WHERE a.recording_id=r.id) AS alias_count, "
                "(SELECT GROUP_CONCAT(group_id) FROM group_recordings g WHERE g.recording_id=r.id) AS group_ids "
                "FROM recordings r ORDER BY r.imported_at DESC"
            ).fetchall()
        return [{**dict(row), "group_ids": row["group_ids"].split(",") if row["group_ids"] else []} for row in rows]

    def list_groups(self) -> list[dict]:
        """Return saved groups with their current recording counts for the sidebar."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT g.id, g.name, COUNT(gr.recording_id) AS recording_count "
                "FROM recording_groups g LEFT JOIN group_recordings gr ON gr.group_id=g.id "
                "GROUP BY g.id ORDER BY g.name COLLATE NOCASE"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_group(self, name: str, recording_ids: list[str]) -> dict:
        """Create a named group and add any selected catalog recordings atomically."""
        normalized = name.strip()
        if not normalized:
            raise ValueError("Group name cannot be empty.")
        group_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO recording_groups(id, name, created_at) VALUES(?,?,?)",
                (group_id, normalized, datetime.now(timezone.utc).isoformat()),
            )
            connection.executemany(
                "INSERT OR IGNORE INTO group_recordings(group_id, recording_id) "
                "SELECT ?, id FROM recordings WHERE id=?",
                [(group_id, recording_id) for recording_id in dict.fromkeys(recording_ids)],
            )
        return next(group for group in self.list_groups() if group["id"] == group_id)

    def add_to_group(self, group_id: str, recording_ids: list[str]) -> dict | None:
        """Add existing recordings to a saved group without duplicate memberships."""
        with self._connect() as connection:
            if not connection.execute("SELECT 1 FROM recording_groups WHERE id=?", (group_id,)).fetchone():
                return None
            connection.executemany(
                "INSERT OR IGNORE INTO group_recordings(group_id, recording_id) "
                "SELECT ?, id FROM recordings WHERE id=?",
                [(group_id, recording_id) for recording_id in dict.fromkeys(recording_ids)],
            )
        return next(group for group in self.list_groups() if group["id"] == group_id)

    def get_recording(self, recording_id: str) -> dict | None:
        """Return a recording and its confirmed filename aliases."""
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["aliases"] = [dict(a) for a in connection.execute(
                "SELECT original_name, sha256, size_bytes, added_at FROM file_aliases WHERE recording_id=? ORDER BY id",
                (recording_id,),
            ).fetchall()]
        return result

    def import_file(self, filename: str, content: BinaryIO, mime_type: str | None) -> tuple[dict, bool, list[dict]]:
        """Hash and persist one upload, returning the row, duplicate flag, and match candidates."""
        original_name = Path(filename or "recording").name
        extension = Path(original_name).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported audio format: {extension or 'file without an extension'}")

        recording_id = str(uuid.uuid4())
        target_dir = self.audio_dir / recording_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / original_name
        digest = hashlib.sha256()
        size = 0
        try:
            with target_path.open("wb") as output:
                while chunk := content.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    output.write(chunk)
            sha256 = digest.hexdigest()
            duration, embedded_date = self._media_metadata(target_path)
            with self._connect() as connection:
                existing = connection.execute("SELECT * FROM recordings WHERE sha256=?", (sha256,)).fetchone()
                if existing:
                    connection.execute("INSERT OR IGNORE INTO file_aliases(recording_id, original_name, sha256, size_bytes, added_at) VALUES(?,?,?,?,?)",
                                       (existing["id"], original_name, sha256, size, datetime.now(timezone.utc).isoformat()))
                    target_path.unlink(missing_ok=True)
                    target_dir.rmdir()
                    return dict(existing), True, []

                candidates = connection.execute(
                    "SELECT id, original_name, size_bytes, duration_seconds FROM recordings WHERE size_bytes=?",
                    (size,),
                ).fetchall()
                possible = [dict(row) for row in candidates if duration is not None and row["duration_seconds"] is not None
                            and abs(duration - row["duration_seconds"]) <= 2.0]
                possible_id = possible[0]["id"] if possible else None
                connection.execute(
                    "INSERT INTO recordings(id,original_name,stored_path,sha256,size_bytes,duration_seconds,media_date,imported_at,mime_type,extension,status,possible_match_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (recording_id, original_name, str(target_path), sha256, size, duration,
                     embedded_date, datetime.now(timezone.utc).isoformat(), mime_type,
                     extension, "untranscribed", possible_id),
                )
            return self.get_recording(recording_id) or {}, False, possible
        except Exception:
            target_path.unlink(missing_ok=True)
            try:
                target_dir.rmdir()
            except OSError:
                pass
            raise

    def confirm_separate(self, recording_id: str) -> dict | None:
        """Clear a possible-match marker after the user confirms two files are distinct."""
        with self._connect() as connection:
            connection.execute("UPDATE recordings SET possible_match_id=NULL WHERE id=?", (recording_id,))
        return self.get_recording(recording_id)

    def set_status(self, recording_id: str, status: str) -> dict | None:
        """Record a user-confirmed existing-transcript status during MVP1 migration."""
        if status not in {"transcribed", "untranscribed"}:
            raise ValueError("Status must be transcribed or untranscribed")
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE recordings SET status=?, status_source='manual' WHERE id=?",
                (status, recording_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get_recording(recording_id)

    def move_to_trash(self, recording_id: str) -> bool:
        """Move the audio file to the OS trash before removing its catalog entry."""
        with self._connect() as connection:
            row = connection.execute("SELECT stored_path FROM recordings WHERE id=?", (recording_id,)).fetchone()
            if not row:
                return False
            path = Path(row["stored_path"])
            if path.exists():
                send2trash(str(path))
            connection.execute("UPDATE recordings SET possible_match_id=NULL WHERE possible_match_id=?", (recording_id,))
            connection.execute("DELETE FROM recordings WHERE id=?", (recording_id,))
            try:
                path.parent.rmdir()
            except OSError:
                pass
        return True

    def confirm_match(self, recording_id: str, canonical_id: str) -> dict | None:
        """Attach a changed-byte file hash and filename to the confirmed canonical recording."""
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
            canonical = connection.execute("SELECT * FROM recordings WHERE id=?", (canonical_id,)).fetchone()
            if not row or not canonical or recording_id == canonical_id:
                return None
            connection.execute("INSERT OR IGNORE INTO file_aliases(recording_id,original_name,sha256,size_bytes,added_at) VALUES(?,?,?,?,?)",
                               (canonical_id, row["original_name"], row["sha256"], row["size_bytes"], datetime.now(timezone.utc).isoformat()))
            connection.execute("DELETE FROM recordings WHERE id=?", (recording_id,))
            Path(row["stored_path"]).unlink(missing_ok=True)
            try:
                Path(row["stored_path"]).parent.rmdir()
            except OSError:
                pass
        return self.get_recording(canonical_id)
