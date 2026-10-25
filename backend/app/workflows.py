"""Persist transcript inputs, reusable pipeline definitions, and stage run history."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import keyring
from .asr_catalog import TRANSCRIPTION_MODELS

KEYRING_SERVICE = "JournalTranscriber"
KEYRING_USERNAME = "openrouter-api-key"


def openrouter_key() -> tuple[str | None, str]:
    """Prefer the saved OS credential and fall back to an environment variable."""
    try:
        secret = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if secret:
            return secret, "Windows Credential Manager"
    except Exception:
        pass
    secret = os.environ.get("OPENROUTER_API_KEY")
    return (secret, "environment variable") if secret else (None, "not configured")


def save_openrouter_key(secret: str) -> None:
    """Store the API key through the platform credential provider, not SQLite."""
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, secret)


def remove_openrouter_key() -> None:
    """Remove a saved OS credential while preserving any environment fallback."""
    try:
        keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass


def check_openrouter_key(secret: str) -> dict:
    """Validate a key with OpenRouter's current-key endpoint without exposing it."""
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {secret}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status == 200:
                return {"valid": True, "message": "Connection successful. OpenRouter accepted the API key."}
            return {"valid": False, "message": f"OpenRouter returned HTTP {response.status} while checking the key."}
    except urllib.error.HTTPError as error:
        if error.code == 401:
            return {"valid": False, "message": "OpenRouter rejected the API key. Check that it is correct and active."}
        if error.code == 403:
            return {"valid": False, "message": "OpenRouter denied this key. Check its permissions and status."}
        return {"valid": False, "message": f"OpenRouter returned HTTP {error.code} while checking the key."}
    except (urllib.error.URLError, TimeoutError) as error:
        reason = getattr(error, "reason", error)
        return {"valid": False, "message": f"Could not reach OpenRouter: {reason}"}


def now() -> str:
    """Return a timezone-aware timestamp suitable for persistent run records."""
    return datetime.now(timezone.utc).isoformat()


def validate_pipeline(config: dict) -> dict:
    """Validate stages and normalize the official output selected as pipeline input."""
    name = str(config.get("name", "")).strip()
    steps = config.get("steps")
    if not name:
        raise ValueError("Pipeline name is required.")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Add at least one pipeline step.")
    seen: set[str] = set()
    normalized = []
    transcription_seen = False
    for index, step in enumerate(steps):
        step_id = str(step.get("id") or uuid.uuid4())
        step_name = str(step.get("name", "")).strip()
        model = str(step.get("model", "")).strip()
        prompt = str(step.get("prompt", "")).strip()
        input_ref = str(step.get("input_ref", "raw"))
        kind = str(step.get("kind", "custom"))
        if kind not in {"transcription", "cleanup", "verification", "summary", "title", "custom"}:
            raise ValueError(f"Step {index + 1}: unsupported stage type.")
        if not step_name:
            raise ValueError(f"Step {index + 1}: name is required.")
        if kind == "transcription":
            if transcription_seen:
                raise ValueError("A pipeline can contain only one transcription stage.")
            if index != 0:
                raise ValueError("The transcription stage must be the first pipeline stage.")
            if model not in TRANSCRIPTION_MODELS:
                raise ValueError(f"Step {index + 1}: choose a supported local transcription model.")
            if input_ref not in {"audio", "raw"}:
                raise ValueError("The transcription stage input must be the audio recording.")
            input_ref = "audio"
            prompt = ""
            step_name = "Transcription"
            transcription_seen = True
        else:
            if not model:
                raise ValueError(f"Step {index + 1}: OpenRouter model ID is required.")
            if not prompt:
                raise ValueError(f"Step {index + 1}: prompt is required.")
            if step_name.casefold() == "transcription":
                raise ValueError("Transcription is a reserved output name for local ASR stages.")
            if input_ref != "raw" and input_ref not in seen:
                raise ValueError(f"Step {index + 1}: input must be raw or an output from an earlier step.")
        normalized.append({"id": step_id, "name": step_name, "model": model, "prompt": prompt,
                           "input_ref": input_ref, "output_format": "text",
                           "kind": kind})
        seen.add(step_id)
    if len(seen) != len(normalized):
        raise ValueError("Each pipeline step needs a unique ID.")
    initial_output_name = str(config.get("initial_output_name", "Transcription")).strip()
    if not initial_output_name:
        raise ValueError("Choose an official output to use as the pipeline input.")
    return {"name": name, "description": str(config.get("description", "")).strip(),
            "initial_output_name": initial_output_name, "steps": normalized}


class WorkflowStore:
    """Own transcript sources, official outputs, their archive, and pipeline history."""

    def __init__(self, database_path: Path) -> None:
        """Initialize workflow tables in the app's existing SQLite database."""
        self.database_path = database_path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS raw_transcripts (
                    id TEXT PRIMARY KEY, recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
                    provider TEXT NOT NULL DEFAULT 'legacy transcript', model TEXT NOT NULL DEFAULT '',
                    UNIQUE(recording_id, version)
                );
                CREATE TABLE IF NOT EXISTS pipelines (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE, description TEXT NOT NULL,
                    config_json TEXT NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    id TEXT PRIMARY KEY, pipeline_id TEXT NOT NULL, pipeline_name TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    started_at TEXT, finished_at TEXT, error TEXT
                );
                CREATE TABLE IF NOT EXISTS run_inputs (
                    run_id TEXT NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
                    recording_id TEXT NOT NULL, raw_version INTEGER NOT NULL, raw_content TEXT NOT NULL,
                    source_output_id TEXT, source_output_name TEXT NOT NULL DEFAULT 'Transcription',
                    PRIMARY KEY(run_id, recording_id)
                );
                CREATE TABLE IF NOT EXISTS stage_runs (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
                    recording_id TEXT NOT NULL, step_id TEXT NOT NULL, step_index INTEGER NOT NULL,
                    step_name TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, prompt TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL, input_ref TEXT NOT NULL, output_format TEXT NOT NULL,
                    status TEXT NOT NULL, input_text TEXT, output_text TEXT, error TEXT,
                    started_at TEXT, finished_at TEXT, UNIQUE(run_id, recording_id, step_id)
                );
                CREATE TABLE IF NOT EXISTS official_outputs (
                    id TEXT PRIMARY KEY,
                    recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
                    name TEXT COLLATE NOCASE NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    run_id TEXT,
                    stage_run_id TEXT,
                    source_id TEXT,
                    created_at TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(recording_id, name)
                );
                CREATE INDEX IF NOT EXISTS official_outputs_recording_order
                    ON official_outputs(recording_id, position);
                CREATE TABLE IF NOT EXISTS output_history (
                    id TEXT PRIMARY KEY,
                    recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    run_id TEXT,
                    stage_run_id TEXT,
                    source_id TEXT,
                    created_at TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    archived_at TEXT NOT NULL,
                    archive_reason TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS output_history_recording_archived
                    ON output_history(recording_id, archived_at DESC);
                CREATE TABLE IF NOT EXISTS workflow_migrations (
                    name TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS output_name_overrides (
                    recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
                    step_id TEXT NOT NULL,
                    output_name TEXT NOT NULL COLLATE NOCASE,
                    PRIMARY KEY(recording_id, step_id)
                );
            """)
            input_columns = {row["name"] for row in db.execute("PRAGMA table_info(run_inputs)").fetchall()}
            if "source_output_id" not in input_columns:
                db.execute("ALTER TABLE run_inputs ADD COLUMN source_output_id TEXT")
            if "source_output_name" not in input_columns:
                db.execute("ALTER TABLE run_inputs ADD COLUMN source_output_name TEXT NOT NULL DEFAULT 'Transcription'")
            transcript_columns = {row["name"] for row in db.execute("PRAGMA table_info(raw_transcripts)").fetchall()}
            if "provider" not in transcript_columns:
                db.execute("ALTER TABLE raw_transcripts ADD COLUMN provider TEXT NOT NULL DEFAULT 'legacy transcript'")
            if "model" not in transcript_columns:
                db.execute("ALTER TABLE raw_transcripts ADD COLUMN model TEXT NOT NULL DEFAULT ''")
            self._backfill_output_library(db)
            self._backfill_transcription_provenance(db)

    def connect(self) -> sqlite3.Connection:
        """Open a foreign-key-enabled row-aware SQLite connection."""
        db = sqlite3.connect(self.database_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def save_raw_transcript(self, recording_id: str, content: str, provider: str = "manual", model: str = "") -> dict:
        """Append raw text and publish it as the current official Transcription output."""
        if not content.strip():
            raise ValueError("Transcript text cannot be empty.")
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM recordings WHERE id=?", (recording_id,)).fetchone():
                raise KeyError("Recording not found.")
            version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM raw_transcripts WHERE recording_id=?", (recording_id,)).fetchone()[0]
            transcript_id = str(uuid.uuid4())
            created = now()
            db.execute(
                "INSERT INTO raw_transcripts(id,recording_id,version,content,created_at,provider,model) VALUES(?,?,?,?,?,?,?)",
                (transcript_id, recording_id, version, content, created, provider, model),
            )
            db.execute("UPDATE recordings SET status='transcribed', status_source='derived' WHERE id=?", (recording_id,))
            self._publish_output(db, {
                "recording_id": recording_id, "name": "Transcription", "kind": "transcription",
                "content": content, "provider": provider, "model": model,
                "source_id": transcript_id, "created_at": created,
            }, archive_reason="replaced")
        official = self.list_official_outputs(recording_id)
        official_transcript = next((item for item in official if item["name"].casefold() == "transcription"), None)
        return {"id": transcript_id, "recording_id": recording_id, "version": version,
                "content": content, "created_at": created, "provider": provider, "model": model,
                "official_output_id": official_transcript["id"] if official_transcript else None}

    def _backfill_output_library(self, db: sqlite3.Connection) -> None:
        """Seed official outputs and archived predecessors from the existing append-only records."""
        migration = "official-output-library-v1"
        if db.execute("SELECT 1 FROM workflow_migrations WHERE name=?", (migration,)).fetchone():
            return
        transcription_runs = self._transcription_provenance(db)
        transcript_rows = db.execute(
            "SELECT id,recording_id,content,created_at,provider,model FROM raw_transcripts ORDER BY created_at,version"
        ).fetchall()
        for row in transcript_rows:
            provenance = transcription_runs.get(row["id"], {})
            self._publish_output(db, {
                "recording_id": row["recording_id"], "name": "Transcription", "kind": "transcription",
                "content": row["content"], "provider": provenance.get("provider") or row["provider"] or "legacy transcript",
                "model": provenance.get("model") or row["model"] or "", "run_id": provenance.get("run_id"),
                "source_id": row["id"], "created_at": row["created_at"],
            }, archive_reason="replaced")
        stage_rows = db.execute(
            "SELECT s.*,p.snapshot_json,p.pipeline_name,p.created_at AS run_created_at "
            "FROM stage_runs s JOIN pipeline_runs p ON p.id=s.run_id "
            "WHERE s.status='succeeded' AND s.output_text IS NOT NULL AND s.provider!='local_asr' "
            "ORDER BY COALESCE(s.finished_at,s.started_at,p.created_at),s.step_index"
        ).fetchall()
        for row in stage_rows:
            try:
                config = json.loads(row["snapshot_json"])
                step = next(item for item in config.get("steps", []) if item.get("id") == row["step_id"])
            except (ValueError, StopIteration):
                step = {}
            self._publish_output(db, {
                "recording_id": row["recording_id"], "name": row["step_name"],
                "kind": step.get("kind", "custom"), "content": row["output_text"],
                "provider": row["provider"], "model": row["model"], "run_id": row["run_id"],
                "stage_run_id": row["id"], "created_at": row["finished_at"] or row["run_created_at"],
            }, archive_reason="replaced")
        db.execute("INSERT INTO workflow_migrations(name,applied_at) VALUES(?,?)", (migration, now()))

    @staticmethod
    def _transcription_provenance(db: sqlite3.Connection) -> dict[str, dict[str, str]]:
        """Link saved raw transcript versions to their successful ASR run metadata."""
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='transcription_runs'").fetchone():
            return {}
        result: dict[str, dict[str, str]] = {}
        rows = db.execute(
            "SELECT id,recording_id,provider,model,result_json FROM transcription_runs WHERE status='succeeded' ORDER BY started_at"
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["result_json"] or "{}")
            except (TypeError, ValueError):
                payload = {}
            transcript_id = payload.get("transcript_id")
            if not transcript_id and payload.get("transcript_version") is not None:
                transcript = db.execute(
                    "SELECT id FROM raw_transcripts WHERE recording_id=? AND version=?",
                    (row["recording_id"], payload["transcript_version"]),
                ).fetchone()
                transcript_id = transcript["id"] if transcript else None
            if transcript_id:
                result[transcript_id] = {
                    "run_id": row["id"], "provider": row["provider"], "model": row["model"],
                }
        return result

    def _backfill_transcription_provenance(self, db: sqlite3.Connection) -> None:
        """Enrich migrated transcript rows from ASR runs already saved in the library."""
        migration = "transcription-output-provenance-v2"
        if db.execute("SELECT 1 FROM workflow_migrations WHERE name=?", (migration,)).fetchone():
            return
        for transcript_id, provenance in self._transcription_provenance(db).items():
            db.execute(
                "UPDATE raw_transcripts SET provider=?,model=? WHERE id=?",
                (provenance["provider"], provenance["model"], transcript_id),
            )
            for table in ("official_outputs", "output_history"):
                db.execute(
                    f"UPDATE {table} SET provider=?,model=?,run_id=? WHERE kind='transcription' AND source_id=?",
                    (provenance["provider"], provenance["model"], provenance["run_id"], transcript_id),
                )
        db.execute("INSERT INTO workflow_migrations(name,applied_at) VALUES(?,?)", (migration, now()))

    @staticmethod
    def _archive_output(db: sqlite3.Connection, output: sqlite3.Row, reason: str, archived_at: str) -> str:
        """Copy an official output into durable history before it is replaced or removed."""
        history_id = output["id"]
        db.execute(
            "INSERT INTO output_history(id,recording_id,name,kind,content,provider,model,run_id,stage_run_id,source_id,created_at,position,archived_at,archive_reason) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (history_id, output["recording_id"], output["name"], output["kind"], output["content"],
             output["provider"], output["model"], output["run_id"], output["stage_run_id"], output["source_id"],
             output["created_at"], output["position"], archived_at, reason),
        )
        return history_id

    def _publish_output(self, db: sqlite3.Connection, output: dict, archive_reason: str = "replaced") -> dict:
        """Promote a named output, archiving the previous official value with the same name."""
        existing = db.execute(
            "SELECT * FROM official_outputs WHERE recording_id=? AND name=? COLLATE NOCASE",
            (output["recording_id"], output["name"]),
        ).fetchone()
        timestamp = output.get("created_at") or now()
        if existing:
            self._archive_output(db, existing, archive_reason, timestamp)
            position = existing["position"]
            db.execute("DELETE FROM official_outputs WHERE id=?", (existing["id"],))
        else:
            if output["kind"] == "transcription":
                position = 0
            elif output.get("position") is not None:
                position = int(output["position"])
                db.execute("UPDATE official_outputs SET position=position+1 WHERE recording_id=? AND kind!='transcription' AND position>=?",
                           (output["recording_id"], position))
            else:
                position = db.execute(
                    "SELECT COALESCE(MAX(position),-1)+1 FROM official_outputs WHERE recording_id=? AND kind!='transcription'",
                    (output["recording_id"],),
                ).fetchone()[0]
        official_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO official_outputs(id,recording_id,name,kind,content,provider,model,run_id,stage_run_id,source_id,created_at,position) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (official_id, output["recording_id"], output["name"], output["kind"], output["content"],
             output.get("provider", ""), output.get("model", ""), output.get("run_id"), output.get("stage_run_id"),
             output.get("source_id"), timestamp, position),
        )
        return dict(db.execute("SELECT * FROM official_outputs WHERE id=?", (official_id,)).fetchone())

    def list_official_outputs(self, recording_id: str) -> list[dict]:
        """Return current outputs with transcription pinned above the user-ordered list."""
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM official_outputs WHERE recording_id=? "
                "ORDER BY CASE WHEN kind='transcription' THEN 0 ELSE 1 END,position,name COLLATE NOCASE",
                (recording_id,),
            ).fetchall()]

    def list_output_history(self, recording_id: str) -> list[dict]:
        """Return archived or replaced outputs newest first, including their provenance."""
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM output_history WHERE recording_id=? ORDER BY archived_at DESC,created_at DESC",
                (recording_id,),
            ).fetchall()]

    def rename_official_output(self, recording_id: str, output_id: str, output_name: str) -> dict | None:
        """Rename one non-transcription output and retain that name across later runs of its stage."""
        name = output_name.strip()
        if not name:
            raise ValueError("Stage name cannot be empty.")
        if name.casefold() == "transcription":
            raise ValueError("Transcription is reserved for local ASR.")
        with self.connect() as db:
            output = db.execute(
                "SELECT * FROM official_outputs WHERE id=? AND recording_id=?",
                (output_id, recording_id),
            ).fetchone()
            if not output:
                return None
            if output["kind"] == "transcription":
                raise ValueError("Transcription cannot be renamed.")
            conflict = db.execute(
                "SELECT 1 FROM official_outputs WHERE recording_id=? AND name=? COLLATE NOCASE AND id!=?",
                (recording_id, name, output_id),
            ).fetchone()
            if conflict:
                raise FileExistsError("This stage name is already used for this recording")
            step = db.execute("SELECT step_id FROM stage_runs WHERE id=?", (output["stage_run_id"],)).fetchone() if output["stage_run_id"] else None
            db.execute("UPDATE official_outputs SET name=? WHERE id=?", (name, output_id))
            if step:
                db.execute(
                    "INSERT INTO output_name_overrides(recording_id,step_id,output_name) VALUES(?,?,?) "
                    "ON CONFLICT(recording_id,step_id) DO UPDATE SET output_name=excluded.output_name",
                    (recording_id, step["step_id"], name),
                )
            renamed = db.execute("SELECT * FROM official_outputs WHERE id=?", (output_id,)).fetchone()
        return dict(renamed) if renamed else None

    def archive_official_output(self, recording_id: str, output_id: str) -> dict | None:
        """Move one current output into previous versions without deleting its content."""
        with self.connect() as db:
            output = db.execute("SELECT * FROM official_outputs WHERE id=? AND recording_id=?", (output_id, recording_id)).fetchone()
            if not output:
                return None
            history_id = self._archive_output(db, output, "removed", now())
            db.execute("DELETE FROM official_outputs WHERE id=?", (output_id,))
            self._normalize_output_positions(db, recording_id)
            row = db.execute("SELECT * FROM output_history WHERE id=?", (history_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _normalize_output_positions(db: sqlite3.Connection, recording_id: str) -> None:
        """Keep non-transcription outputs in a compact stable order after removals."""
        rows = db.execute("SELECT id FROM official_outputs WHERE recording_id=? AND kind!='transcription' ORDER BY position,name COLLATE NOCASE", (recording_id,)).fetchall()
        for position, row in enumerate(rows):
            db.execute("UPDATE official_outputs SET position=? WHERE id=?", (position, row["id"]))

    def move_official_output(self, recording_id: str, output_id: str, direction: str) -> list[dict] | None:
        """Move a non-transcription output one place while keeping transcription pinned."""
        if direction not in {"up", "down"}:
            raise ValueError("Direction must be up or down.")
        with self.connect() as db:
            current = db.execute("SELECT * FROM official_outputs WHERE id=? AND recording_id=?", (output_id, recording_id)).fetchone()
            if not current:
                return None
            if current["kind"] == "transcription":
                raise ValueError("Transcription is always shown first.")
            rows = db.execute("SELECT * FROM official_outputs WHERE recording_id=? AND kind!='transcription' ORDER BY position,name COLLATE NOCASE", (recording_id,)).fetchall()
            index = next(i for i, row in enumerate(rows) if row["id"] == output_id)
            target = index + (-1 if direction == "up" else 1)
            if 0 <= target < len(rows):
                first, second = rows[index], rows[target]
                db.execute("UPDATE official_outputs SET position=-1 WHERE id=?", (first["id"],))
                db.execute("UPDATE official_outputs SET position=? WHERE id=?", (first["position"], second["id"]))
                db.execute("UPDATE official_outputs SET position=? WHERE id=?", (second["position"], first["id"]))
        return self.list_official_outputs(recording_id)

    def restore_output(self, recording_id: str, history_id: str, output_name: str | None = None) -> dict:
        """Restore archived content as a new official output, requiring a new name on conflict."""
        with self.connect() as db:
            archived = db.execute("SELECT * FROM output_history WHERE id=? AND recording_id=?", (history_id, recording_id)).fetchone()
            if not archived:
                raise KeyError("Previous output not found.")
            name = (output_name or archived["name"]).strip()
            if not name:
                raise ValueError("Output name cannot be empty.")
            conflict = db.execute("SELECT 1 FROM official_outputs WHERE recording_id=? AND name=? COLLATE NOCASE", (recording_id, name)).fetchone()
            if conflict:
                raise FileExistsError("An official output already uses that name. Choose a different name to restore this version.")
            restored = self._publish_output(db, {
                "recording_id": recording_id, "name": name, "kind": archived["kind"],
                "content": archived["content"], "provider": archived["provider"], "model": archived["model"],
                "run_id": archived["run_id"], "stage_run_id": archived["stage_run_id"],
                "source_id": archived["source_id"], "created_at": archived["created_at"], "position": archived["position"],
            })
        return restored

    def complete_stage(self, stage_id: str, output_text: str, kind: str) -> None:
        """Atomically save a successful stage and publish named text outputs as official."""
        finished = now()
        with self.connect() as db:
            stage = db.execute(
                "SELECT s.*,p.pipeline_name FROM stage_runs s JOIN pipeline_runs p ON p.id=s.run_id WHERE s.id=?",
                (stage_id,),
            ).fetchone()
            if not stage:
                raise KeyError("Pipeline stage not found.")
            db.execute("UPDATE stage_runs SET status='succeeded',output_text=?,finished_at=?,error=NULL WHERE id=?", (output_text, finished, stage_id))
            if kind != "transcription":
                name_override = db.execute(
                    "SELECT output_name FROM output_name_overrides WHERE recording_id=? AND step_id=?",
                    (stage["recording_id"], stage["step_id"]),
                ).fetchone()
                self._publish_output(db, {
                    "recording_id": stage["recording_id"], "name": name_override["output_name"] if name_override else stage["step_name"], "kind": kind,
                    "content": output_text, "provider": stage["provider"], "model": stage["model"],
                    "run_id": stage["run_id"], "stage_run_id": stage_id, "created_at": finished,
                })

    def get_raw_transcripts(self, recording_id: str) -> list[dict]:
        """Return raw transcript versions newest first for source review."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,recording_id,version,content,created_at,provider,model FROM raw_transcripts WHERE recording_id=? ORDER BY version DESC",
                (recording_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_transcript_word_alignments(self, recording_id: str, transcript_ids: list[str]) -> dict[str, dict]:
        """Match saved Whisper word timings and probabilities to exact raw transcript versions."""
        requested = set(transcript_ids)
        if not requested:
            return {}
        alignments: dict[str, dict] = {}
        with self.connect() as db:
            valid_ids = {row["id"] for row in db.execute(
                "SELECT id FROM raw_transcripts WHERE recording_id=?", (recording_id,),
            ).fetchall()}
            requested.intersection_update(valid_ids)
            if not requested:
                return {}
            runs = db.execute(
                "SELECT result_json FROM transcription_runs WHERE recording_id=? AND status='succeeded' AND result_json IS NOT NULL ORDER BY finished_at DESC",
                (recording_id,),
            ).fetchall()
        for run in runs:
            result = json.loads(run["result_json"])
            transcript_id = result.get("transcript_id")
            if transcript_id not in requested or transcript_id in alignments:
                continue
            segment_words = [word for segment in result.get("segments", []) for word in segment.get("words", [])]
            normalized = result.get("words") or segment_words
            words = []
            for index, word in enumerate(normalized):
                source_word = segment_words[index] if index < len(segment_words) else {}
                probability = word.get("probability", source_word.get("probability"))
                try:
                    probability = float(probability) if probability is not None else None
                except (TypeError, ValueError):
                    probability = None
                words.append({
                    "start": float(word["start"]),
                    "end": float(word["end"]),
                    "text": word.get("text", word.get("word", "")),
                    "probability": probability,
                })
            alignments[transcript_id] = {"transcript_id": transcript_id, "words": words}
        return alignments

    def list_pipelines(self) -> list[dict]:
        """List saved pipelines without exposing run output payloads."""
        with self.connect() as db:
            rows = db.execute("SELECT id,name,description,version,created_at,updated_at FROM pipelines ORDER BY name COLLATE NOCASE").fetchall()
        return [dict(row) for row in rows]

    def get_pipeline(self, pipeline_id: str) -> dict | None:
        """Load one saved pipeline configuration."""
        with self.connect() as db:
            row = db.execute("SELECT * FROM pipelines WHERE id=?", (pipeline_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["config"] = validate_pipeline(json.loads(result.pop("config_json")))
        return result

    def save_pipeline(self, config: dict, pipeline_id: str | None = None) -> dict:
        """Create or update a pipeline while keeping prior runs' snapshots unchanged."""
        clean = validate_pipeline(config)
        pipeline_id = pipeline_id or str(uuid.uuid4())
        timestamp = now()
        with self.connect() as db:
            existing = db.execute("SELECT version,created_at FROM pipelines WHERE id=?", (pipeline_id,)).fetchone()
            version = existing["version"] + 1 if existing else 1
            created = existing["created_at"] if existing else timestamp
            db.execute("""INSERT INTO pipelines(id,name,description,config_json,version,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,
                config_json=excluded.config_json,version=excluded.version,updated_at=excluded.updated_at""",
                (pipeline_id, clean["name"], clean["description"], json.dumps(clean), version, created, timestamp))
        return self.get_pipeline(pipeline_id) or {}

    def duplicate_pipeline(self, pipeline_id: str) -> dict | None:
        """Copy a pipeline configuration under a distinct name and fresh step IDs."""
        source = self.get_pipeline(pipeline_id)
        if not source:
            return None
        config = source["config"]
        config["name"] = f"{source['name']} copy"
        for step in config["steps"]:
            step["id"] = str(uuid.uuid4())
        return self.save_pipeline(config)

    def create_run(self, pipeline_id: str, recording_ids: list[str]) -> dict:
        """Snapshot the chosen official output per recording, or audio for a first ASR stage."""
        pipeline = self.get_pipeline(pipeline_id)
        if not pipeline:
            raise KeyError("Pipeline not found.")
        if not recording_ids:
            raise ValueError("Select at least one recording.")
        run_id = str(uuid.uuid4())
        snapshot = {**pipeline["config"], "pipeline_id": pipeline_id, "pipeline_version": pipeline["version"]}
        begins_with_transcription = snapshot["steps"][0]["kind"] == "transcription"
        initial_output_name = snapshot.get("initial_output_name", "Transcription")
        with self.connect() as db:
            db.execute("INSERT INTO pipeline_runs(id,pipeline_id,pipeline_name,snapshot_json,status,created_at) VALUES(?,?,?,?,?,?)",
                       (run_id, pipeline_id, pipeline["name"], json.dumps(snapshot), "queued", now()))
            for recording_id in dict.fromkeys(recording_ids):
                if not db.execute("SELECT 1 FROM recordings WHERE id=?", (recording_id,)).fetchone():
                    raise KeyError(f"Recording {recording_id} was not found.")
                selected_output = None
                raw_version = 0
                if not begins_with_transcription:
                    transcription = db.execute(
                        "SELECT id FROM official_outputs WHERE recording_id=? AND kind='transcription' LIMIT 1",
                        (recording_id,),
                    ).fetchone()
                    if not transcription:
                        raise ValueError(f"Recording {recording_id} has no official transcription. Transcribe it before running text stages.")
                    selected_output = db.execute(
                        "SELECT * FROM official_outputs WHERE recording_id=? AND name=? COLLATE NOCASE",
                        (recording_id, initial_output_name),
                    ).fetchone()
                    if not selected_output:
                        raise ValueError(f"Recording {recording_id} has no official output named '{initial_output_name}'. Choose an output available for every selected recording.")
                    if selected_output["kind"] == "transcription" and selected_output["source_id"]:
                        version_row = db.execute("SELECT version FROM raw_transcripts WHERE id=?", (selected_output["source_id"],)).fetchone()
                        raw_version = version_row["version"] if version_row else 0
                db.execute(
                    "INSERT INTO run_inputs(run_id,recording_id,raw_version,raw_content,source_output_id,source_output_name) VALUES(?,?,?,?,?,?)",
                    (run_id, recording_id, raw_version,
                     "" if begins_with_transcription else selected_output["content"],
                     selected_output["id"] if selected_output else None,
                     selected_output["name"] if selected_output else "Audio recording"),
                )
                for index, step in enumerate(snapshot["steps"]):
                    db.execute("""INSERT INTO stage_runs(id,run_id,recording_id,step_id,step_index,step_name,provider,model,
                        prompt,prompt_hash,input_ref,output_format,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (str(uuid.uuid4()), run_id, recording_id, step["id"], index, step["name"],
                         "local_asr" if step["kind"] == "transcription" else "openrouter", step["model"],
                         step["prompt"], hashlib.sha256(step["prompt"].encode()).hexdigest(), step["input_ref"], step["output_format"], "queued"))
        return self.get_run(run_id) or {}

    def get_run(self, run_id: str) -> dict | None:
        """Return a run and its per-recording, per-stage statuses and outputs."""
        with self.connect() as db:
            run = db.execute("SELECT * FROM pipeline_runs WHERE id=?", (run_id,)).fetchone()
            if not run:
                return None
            result = dict(run)
            result["pipeline_snapshot"] = json.loads(result.pop("snapshot_json"))
            result["inputs"] = [dict(row) for row in db.execute(
                "SELECT i.recording_id,i.raw_version,i.raw_content,i.source_output_id,i.source_output_name,COALESCE(r.original_name,'Deleted recording') AS original_name "
                "FROM run_inputs i LEFT JOIN recordings r ON r.id=i.recording_id WHERE i.run_id=? ORDER BY i.recording_id", (run_id,)).fetchall()]
            result["stages"] = [dict(row) for row in db.execute(
                "SELECT s.*, COALESCE(r.original_name,'Deleted recording') AS original_name FROM stage_runs s "
                "LEFT JOIN recordings r ON r.id=s.recording_id WHERE s.run_id=? ORDER BY s.recording_id,s.step_index", (run_id,)).fetchall()]
        return result

    def list_runs(self, limit: int = 30) -> list[dict]:
        """List recent batch runs with compact progress counts."""
        with self.connect() as db:
            rows = db.execute("""SELECT p.id,p.pipeline_name,p.status,p.created_at,p.finished_at,
                COUNT(s.id) AS total_stages,SUM(CASE WHEN s.status='succeeded' THEN 1 ELSE 0 END) AS succeeded_stages,
                SUM(CASE WHEN s.status='failed' THEN 1 ELSE 0 END) AS failed_stages
                FROM pipeline_runs p LEFT JOIN stage_runs s ON s.run_id=p.id GROUP BY p.id ORDER BY p.created_at DESC LIMIT ?""", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def list_recording_run_outputs(self, recording_id: str, limit: int = 50) -> list[dict]:
        """Return recent saved runs and stage outputs for one recording, newest first."""
        with self.connect() as db:
            rows = db.execute("""SELECT p.id,p.pipeline_name,p.status AS run_status,p.created_at,p.finished_at,
                    s.id AS stage_run_id,s.step_name,s.step_index,s.provider,s.model,s.status AS stage_status,
                    s.output_text,s.error,s.started_at,s.finished_at AS stage_finished_at
                FROM pipeline_runs p
                JOIN stage_runs s ON s.run_id=p.id
                WHERE s.recording_id=?
                  AND p.id IN (SELECT p2.id FROM pipeline_runs p2 JOIN stage_runs s2 ON s2.run_id=p2.id
                               WHERE s2.recording_id=? GROUP BY p2.id ORDER BY p2.created_at DESC LIMIT ?)
                ORDER BY p.created_at DESC,s.step_index ASC""", (recording_id, recording_id, limit)).fetchall()
        runs: dict[str, dict] = {}
        for row in rows:
            item = dict(row)
            run_id = item["id"]
            run = runs.setdefault(run_id, {
                "id": run_id,
                "pipeline_name": item["pipeline_name"],
                "status": item["run_status"],
                "created_at": item["created_at"],
                "finished_at": item["finished_at"],
                "stages": [],
            })
            run["stages"].append({
                "id": item["stage_run_id"],
                "step_name": item["step_name"],
                "step_index": item["step_index"],
                "provider": item["provider"],
                "model": item["model"],
                "status": item["stage_status"],
                "output_text": item["output_text"],
                "error": item["error"],
                "started_at": item["started_at"],
                "finished_at": item["stage_finished_at"],
            })
        return list(runs.values())

    def claim_run(self, run_id: str) -> dict | None:
        """Mark a queued run active and return its immutable input snapshot."""
        with self.connect() as db:
            row = db.execute("SELECT * FROM pipeline_runs WHERE id=?", (run_id,)).fetchone()
            if not row or row["status"] not in {"queued", "running"}:
                return None
            db.execute("UPDATE pipeline_runs SET status='running',started_at=COALESCE(started_at,?) WHERE id=?", (now(), run_id))
            return dict(row)

    def run_inputs(self, run_id: str) -> list[dict]:
        """Load the frozen raw input texts for every item in the batch."""
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT i.*,COALESCE(r.original_name,'Deleted recording') AS original_name FROM run_inputs i "
                "LEFT JOIN recordings r ON r.id=i.recording_id WHERE i.run_id=? ORDER BY i.recording_id", (run_id,)
            ).fetchall()]

    def update_run_input(self, run_id: str, recording_id: str, transcript: dict) -> None:
        """Attach the newly transcribed raw version to its active pipeline input snapshot."""
        with self.connect() as db:
            db.execute(
                "UPDATE run_inputs SET raw_version=?,raw_content=?,source_output_id=?,source_output_name='Transcription' WHERE run_id=? AND recording_id=?",
                (transcript["version"], transcript["content"], transcript.get("official_output_id"), run_id, recording_id),
            )

    def set_stage(self, stage_id: str, **fields: str | None) -> None:
        """Update a stage's state, exact input/output text, and error details."""
        allowed = {"status", "input_text", "output_text", "error", "started_at", "finished_at"}
        fields = {key: value for key, value in fields.items() if key in allowed}
        if not fields:
            return
        with self.connect() as db:
            db.execute(f"UPDATE stage_runs SET {','.join(f'{key}=?' for key in fields)} WHERE id=?", (*fields.values(), stage_id))

    def finish_run(self, run_id: str) -> None:
        """Set batch status from its stage results after all work is attempted."""
        with self.connect() as db:
            failed = db.execute("SELECT COUNT(*) FROM stage_runs WHERE run_id=? AND status='failed'", (run_id,)).fetchone()[0]
            db.execute("UPDATE pipeline_runs SET status=?,finished_at=? WHERE id=?", ("failed" if failed else "succeeded", now(), run_id))

    def retry_run(self, run_id: str) -> dict | None:
        """Reset only failed stages so completed stages and outputs remain intact."""
        with self.connect() as db:
            row = db.execute("SELECT id FROM pipeline_runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                return None
            db.execute("UPDATE stage_runs SET status='queued',error=NULL,started_at=NULL,finished_at=NULL WHERE run_id=? AND status='failed'", (run_id,))
            db.execute("UPDATE pipeline_runs SET status='queued',finished_at=NULL,error=NULL WHERE id=?", (run_id,))
        return self.get_run(run_id)


class PipelineRunner:
    """Run one persisted pipeline at a time and resume queued work after restart."""

    def __init__(self, store: WorkflowStore, transcriber=None) -> None:
        """Create a serial worker with an optional local ASR adapter and recover queued runs."""
        self.store = store
        self.transcriber = transcriber
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="journal-pipeline")
        with store.connect() as db:
            db.execute("UPDATE pipeline_runs SET status='queued' WHERE status='running'")
            db.execute("UPDATE stage_runs SET status='queued' WHERE status='running'")
            queued = [row[0] for row in db.execute("SELECT id FROM pipeline_runs WHERE status='queued'").fetchall()]
        for run_id in queued:
            self.submit(run_id)

    def submit(self, run_id: str) -> None:
        """Schedule a saved run on the single background worker."""
        self.pool.submit(self._execute, run_id)

    def _execute(self, run_id: str) -> None:
        """Execute queued stages in order, preserving completed outputs on errors."""
        run = self.store.claim_run(run_id)
        if not run:
            return
        snapshot = json.loads(run["snapshot_json"])
        inputs = self.store.run_inputs(run_id)
        try:
            for item in inputs:
                prior_outputs: dict[str, str] = {}
                for step in snapshot["steps"]:
                    with self.store.connect() as db:
                        stage = db.execute("SELECT * FROM stage_runs WHERE run_id=? AND recording_id=? AND step_id=?", (run_id, item["recording_id"], step["id"])).fetchone()
                    if stage["status"] == "succeeded":
                        prior_outputs[step["id"]] = stage["output_text"] or ""
                        continue
                    if step["kind"] == "transcription":
                        input_text = f"Audio file: {item['original_name']}"
                    else:
                        input_text = item["raw_content"] if step["input_ref"] == "raw" else prior_outputs.get(step["input_ref"])
                    if input_text is None:
                        self.store.set_stage(stage["id"], status="failed", error="The configured upstream output is unavailable.", finished_at=now())
                        continue
                    self.store.set_stage(stage["id"], status="running", input_text=input_text, started_at=now(), error=None)
                    try:
                        if step["kind"] == "transcription":
                            if not self.transcriber:
                                raise RuntimeError("Local transcription is not configured for pipeline runs.")
                            result = self.transcriber.transcribe_for_pipeline(item["recording_id"], step["model"])
                            output = result["text"]
                            self.store.update_run_input(run_id, item["recording_id"], {
                                "version": result["transcript_version"], "content": output,
                                "official_output_id": result.get("official_output_id"),
                            })
                            item["raw_version"] = result["transcript_version"]
                            item["raw_content"] = output
                        else:
                            output = self._call_openrouter(step, input_text)
                        self.store.complete_stage(stage["id"], output, step["kind"])
                        prior_outputs[step["id"]] = output
                    except Exception as error:
                        self.store.set_stage(stage["id"], status="failed", error=str(error), finished_at=now())
                        break
            self.store.finish_run(run_id)
        except Exception as error:
            with self.store.connect() as db:
                db.execute("UPDATE pipeline_runs SET status='failed',finished_at=?,error=? WHERE id=?", (now(), str(error), run_id))

    @staticmethod
    def _call_openrouter(step: dict, input_text: str) -> str:
        """Send one explicitly requested transcript stage to OpenRouter."""
        api_key, _ = openrouter_key()
        if not api_key:
            raise RuntimeError("Add an OpenRouter API key in Library settings or set OPENROUTER_API_KEY in the API environment.")
        payload = {"model": step["model"], "messages": [{"role": "user", "content": f"{step['prompt']}\n\nInput transcript:\n{input_text}"}]}
        request = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "HTTP-Referer": "http://localhost:5173", "X-Title": "Journal Transcriber"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"OpenRouter returned HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise RuntimeError(f"OpenRouter request failed: {error}") from error
        try:
            output = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise RuntimeError("OpenRouter response did not contain a message output.") from error
        if not isinstance(output, str) or not output.strip():
            raise RuntimeError("OpenRouter returned an empty output.")
        return output
