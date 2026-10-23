"""FastAPI routes for importing files and browsing the local recording catalog."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .storage import Catalog
from .workflows import PipelineRunner, WorkflowStore

app = FastAPI(title="Journal Transcriber Local API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["*"],
)
catalog = Catalog()
workflow_store = WorkflowStore(catalog.db_path)
pipeline_runner = PipelineRunner(workflow_store)


class StatusUpdate(BaseModel):
    """Request body for the user's known-transcription status."""
    status: str


class DeleteRecordings(BaseModel):
    """Recording IDs the user confirmed moving to the system trash."""
    ids: list[str]


class GroupRequest(BaseModel):
    """Group creation or membership request from selected catalog rows."""
    name: str | None = None
    recording_ids: list[str] = Field(default_factory=list)


class RawTranscriptSave(BaseModel):
    """Raw transcript text supplied from an existing transcript or safe fixture."""
    content: str


class PipelineConfig(BaseModel):
    """User-authored, non-executable pipeline configuration."""
    name: str
    description: str = ""
    steps: list[dict]


class PipelineRunRequest(BaseModel):
    """Recordings chosen for one single or batch workflow run."""
    recording_ids: list[str]


@app.get("/api/health")
def health() -> dict:
    """Expose a lightweight readiness check for the frontend."""
    return {"ok": True, "library_root": str(catalog.root)}


@app.get("/api/recordings")
def list_recordings() -> list[dict]:
    """List catalog entries for the table and summary cards."""
    return catalog.list_recordings()


@app.get("/api/groups")
def list_groups() -> list[dict]:
    """List saved recording groups and their sidebar counts."""
    return catalog.list_groups()


@app.post("/api/groups")
def create_group(request: GroupRequest) -> dict:
    """Create a group and optionally assign selected recordings to it."""
    try:
        return catalog.create_group(request.name or "", request.recording_ids)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="A group with that name already exists.") from error


@app.post("/api/groups/{group_id}/recordings")
def add_recordings_to_group(group_id: str, request: GroupRequest) -> dict:
    """Add the selected recordings to an existing group."""
    group = catalog.add_to_group(group_id, request.recording_ids)
    if not group:
        raise HTTPException(status_code=404, detail="Group not found")
    return group


@app.get("/api/recordings/{recording_id}")
def get_recording(recording_id: str) -> dict:
    """Return detail fields and confirmed filename aliases for the side panel."""
    recording = catalog.get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


@app.get("/api/recordings/{recording_id}/transcripts")
def get_raw_transcripts(recording_id: str) -> list[dict]:
    """List preserved raw transcript versions for the selected recording."""
    if not catalog.get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    return workflow_store.get_raw_transcripts(recording_id)


@app.post("/api/recordings/{recording_id}/transcripts")
def save_raw_transcript(recording_id: str, request: RawTranscriptSave) -> dict:
    """Save a raw transcript as a new version and update derived transcription status."""
    try:
        return workflow_store.save_raw_transcript(recording_id, request.content)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/pipelines")
def list_pipelines() -> list[dict]:
    """List saved text-processing pipeline configurations."""
    return workflow_store.list_pipelines()


@app.post("/api/pipelines")
def save_pipeline(request: PipelineConfig) -> dict:
    """Create or update a validated pipeline configuration."""
    try:
        return workflow_store.save_pipeline(request.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="A pipeline with that name already exists.") from error


@app.get("/api/pipelines/{pipeline_id}")
def get_pipeline(pipeline_id: str) -> dict:
    """Return a pipeline's current editable configuration."""
    pipeline = workflow_store.get_pipeline(pipeline_id)
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline


@app.put("/api/pipelines/{pipeline_id}")
def update_pipeline(pipeline_id: str, request: PipelineConfig) -> dict:
    """Save a new pipeline version while preserving existing run snapshots."""
    if not workflow_store.get_pipeline(pipeline_id):
        raise HTTPException(status_code=404, detail="Pipeline not found")
    try:
        return workflow_store.save_pipeline(request.model_dump(), pipeline_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="A pipeline with that name already exists.") from error


@app.post("/api/pipelines/{pipeline_id}/duplicate")
def duplicate_pipeline(pipeline_id: str) -> dict:
    """Copy a pipeline configuration so it can be adapted independently."""
    try:
        pipeline = workflow_store.duplicate_pipeline(pipeline_id)
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="The copy name is already in use.") from error
    if not pipeline:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return pipeline


@app.post("/api/pipelines/{pipeline_id}/runs")
def start_pipeline_run(pipeline_id: str, request: PipelineRunRequest) -> dict:
    """Queue a pipeline for the selected recordings and preserve their input snapshot."""
    try:
        run = workflow_store.create_run(pipeline_id, request.recording_ids)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    pipeline_runner.submit(run["id"])
    return run


@app.get("/api/pipeline-runs")
def list_pipeline_runs() -> list[dict]:
    """List recent runs with per-stage progress counts."""
    return workflow_store.list_runs()


@app.get("/api/pipeline-runs/{run_id}")
def get_pipeline_run(run_id: str) -> dict:
    """Return all stage statuses, outputs, and errors for a batch run."""
    run = workflow_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return run


@app.post("/api/pipeline-runs/{run_id}/retry")
def retry_pipeline_run(run_id: str) -> dict:
    """Retry failed stages while retaining already-succeeded stage outputs."""
    run = workflow_store.retry_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    pipeline_runner.submit(run_id)
    return run


@app.get("/api/recordings/{recording_id}/audio")
def get_audio(recording_id: str) -> FileResponse:
    """Serve a local recording for future playback controls in the review panel."""
    recording = catalog.get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    path = Path(recording["stored_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio file is missing from the library")
    return FileResponse(path, media_type=recording["mime_type"] or "application/octet-stream")


@app.post("/api/recordings/import")
async def import_recordings(
    files: list[UploadFile] = File(...),
) -> dict:
    """Import a batch while reporting per-file errors without aborting valid files."""
    imported: list[dict] = []
    errors: list[dict] = []
    for upload in files:
        try:
            result, duplicate, candidates = catalog.import_file(
                upload.filename or "recording",
                upload.file,
                upload.content_type,
            )
            imported.append({"recording": result, "duplicate": duplicate, "possible_matches": candidates})
        except ValueError as error:
            errors.append({"name": upload.filename or "recording", "error": str(error)})
        except OSError as error:
            errors.append({"name": upload.filename or "recording", "error": f"Could not store file: {error}"})
        finally:
            await upload.close()
    return {"imported": imported, "errors": errors}


@app.post("/api/recordings/{recording_id}/confirm-separate")
def confirm_separate(recording_id: str) -> dict:
    """Dismiss a metadata-based possible-match warning after user review."""
    recording = catalog.confirm_separate(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


@app.post("/api/recordings/{recording_id}/confirm-match/{canonical_id}")
def confirm_match(recording_id: str, canonical_id: str) -> dict:
    """Confirm two differently encoded files belong to one catalog recording."""
    recording = catalog.confirm_match(recording_id, canonical_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording or possible match not found")
    return recording


@app.patch("/api/recordings/{recording_id}/status")
def update_status(recording_id: str, update: StatusUpdate) -> dict:
    """Save a user's known transcript status while legacy transcript files are outside the library."""
    try:
        recording = catalog.set_status(recording_id, update.status)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    return recording


@app.delete("/api/recordings")
def delete_recordings(request: DeleteRecordings) -> dict:
    """Move each requested recording to system trash, reporting per-file failures."""
    deleted: list[str] = []
    errors: list[dict[str, str]] = []
    for recording_id in dict.fromkeys(request.ids):
        try:
            if catalog.move_to_trash(recording_id):
                deleted.append(recording_id)
            else:
                errors.append({"id": recording_id, "error": "Recording not found."})
        except OSError as error:
            errors.append({"id": recording_id, "error": str(error)})
    return {"deleted": deleted, "errors": errors}
