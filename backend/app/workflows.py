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


def now() -> str:
    """Return a timezone-aware timestamp suitable for persistent run records."""
    return datetime.now(timezone.utc).isoformat()


def validate_pipeline(config: dict) -> dict:
    """Check stage names, prompts, models, output formats, and prior-step bindings."""
    name = str(config.get("name", "")).strip()
    steps = config.get("steps")
    if not name:
        raise ValueError("Pipeline name is required.")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Add at least one pipeline step.")
    seen: set[str] = set()
    normalized = []
    for index, step in enumerate(steps):
        step_id = str(step.get("id") or uuid.uuid4())
        step_name = str(step.get("name", "")).strip()
        model = str(step.get("model", "")).strip()
        prompt = str(step.get("prompt", "")).strip()
        input_ref = str(step.get("input_ref", "raw"))
        output_format = str(step.get("output_format", "text"))
        if not step_name:
            raise ValueError(f"Step {index + 1}: name is required.")
        if not model:
            raise ValueError(f"Step {index + 1}: OpenRouter model ID is required.")
        if not prompt:
            raise ValueError(f"Step {index + 1}: prompt is required.")
        if input_ref != "raw" and input_ref not in seen:
            raise ValueError(f"Step {index + 1}: input must be raw or an output from an earlier step.")
        if output_format not in {"text", "json"}:
            raise ValueError(f"Step {index + 1}: output format must be text or JSON.")
        normalized.append({"id": step_id, "name": step_name, "model": model, "prompt": prompt,
                           "input_ref": input_ref, "output_format": output_format,
                           "kind": str(step.get("kind", "custom"))})
        seen.add(step_id)
    if len(seen) != len(normalized):
        raise ValueError("Each pipeline step needs a unique ID.")
    return {"name": name, "description": str(config.get("description", "")).strip(), "steps": normalized}


class WorkflowStore:
    """Own versioned raw transcript inputs, pipeline snapshots, and stage outputs."""

    def __init__(self, database_path: Path) -> None:
        """Initialize workflow tables in the app's existing SQLite database."""
        self.database_path = database_path
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS raw_transcripts (
                    id TEXT PRIMARY KEY, recording_id TEXT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL,
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
            """)

    def connect(self) -> sqlite3.Connection:
        """Open a foreign-key-enabled row-aware SQLite connection."""
        db = sqlite3.connect(self.database_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def save_raw_transcript(self, recording_id: str, content: str) -> dict:
        """Append a raw transcript version rather than overwriting earlier source text."""
        if not content.strip():
            raise ValueError("Transcript text cannot be empty.")
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM recordings WHERE id=?", (recording_id,)).fetchone():
                raise KeyError("Recording not found.")
            version = db.execute("SELECT COALESCE(MAX(version),0)+1 FROM raw_transcripts WHERE recording_id=?", (recording_id,)).fetchone()[0]
            transcript_id = str(uuid.uuid4())
            created = now()
            db.execute("INSERT INTO raw_transcripts VALUES(?,?,?,?,?)", (transcript_id, recording_id, version, content, created))
            db.execute("UPDATE recordings SET status='transcribed', status_source='derived' WHERE id=?", (recording_id,))
        return {"id": transcript_id, "recording_id": recording_id, "version": version, "content": content, "created_at": created}

    def get_raw_transcripts(self, recording_id: str) -> list[dict]:
        """Return raw transcript versions newest first for source review."""
        with self.connect() as db:
            rows = db.execute("SELECT id, recording_id, version, content, created_at FROM raw_transcripts WHERE recording_id=? ORDER BY version DESC", (recording_id,)).fetchall()
        return [dict(row) for row in rows]

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
        result["config"] = json.loads(result.pop("config_json"))
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
        """Snapshot a pipeline and raw inputs for reproducible single or batch execution."""
        pipeline = self.get_pipeline(pipeline_id)
        if not pipeline:
            raise KeyError("Pipeline not found.")
        if not recording_ids:
            raise ValueError("Select at least one recording.")
        run_id = str(uuid.uuid4())
        snapshot = {**pipeline["config"], "pipeline_id": pipeline_id, "pipeline_version": pipeline["version"]}
        with self.connect() as db:
            db.execute("INSERT INTO pipeline_runs(id,pipeline_id,pipeline_name,snapshot_json,status,created_at) VALUES(?,?,?,?,?,?)",
                       (run_id, pipeline_id, pipeline["name"], json.dumps(snapshot), "queued", now()))
            for recording_id in dict.fromkeys(recording_ids):
                raw = db.execute("SELECT version,content FROM raw_transcripts WHERE recording_id=? ORDER BY version DESC LIMIT 1", (recording_id,)).fetchone()
                if not raw:
                    raise ValueError(f"Recording {recording_id} has no saved raw transcript.")
                db.execute("INSERT INTO run_inputs VALUES(?,?,?,?)", (run_id, recording_id, raw["version"], raw["content"]))
                for index, step in enumerate(snapshot["steps"]):
                    db.execute("""INSERT INTO stage_runs(id,run_id,recording_id,step_id,step_index,step_name,provider,model,
                        prompt,prompt_hash,input_ref,output_format,status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (str(uuid.uuid4()), run_id, recording_id, step["id"], index, step["name"], "openrouter", step["model"],
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
            return [dict(row) for row in db.execute("SELECT * FROM run_inputs WHERE run_id=? ORDER BY recording_id", (run_id,)).fetchall()]

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

    def __init__(self, store: WorkflowStore) -> None:
        """Create a serial worker and recover queued or interrupted runs."""
        self.store = store
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
                    input_text = item["raw_content"] if step["input_ref"] == "raw" else prior_outputs.get(step["input_ref"])
                    if input_text is None:
                        self.store.set_stage(stage["id"], status="failed", error="The configured upstream output is unavailable.", finished_at=now())
                        continue
                    self.store.set_stage(stage["id"], status="running", input_text=input_text, started_at=now(), error=None)
                    try:
                        output = self._call_openrouter(step, input_text)
                        self.store.set_stage(stage["id"], status="succeeded", output_text=output, finished_at=now())
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
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("Set OPENROUTER_API_KEY in the environment, then restart the local API.")
        payload = {"model": step["model"], "messages": [{"role": "user", "content": f"{step['prompt']}\n\nInput transcript:\n{input_text}"}],
                   "response_format": {"type": "json_object"}} if step["output_format"] == "json" else {
                       "model": step["model"], "messages": [{"role": "user", "content": f"{step['prompt']}\n\nInput transcript:\n{input_text}"}]}
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
        if step["output_format"] == "json":
            try:
                json.loads(output)
            except json.JSONDecodeError as error:
                raise RuntimeError("The model output was not valid JSON as requested.") from error
        return output
