"""FastAPI routes for importing files and browsing the local recording catalog."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .audio_media import AudioMediaService
from .storage import Catalog
from .transcription import MODEL_ID, LocalWhisper, list_transcription_models
from .model_catalog import list_openrouter_models
from .workflows import (
    PipelineRunner,
    WorkflowStore,
    check_openrouter_key,
    openrouter_key,
    remove_openrouter_key,
    save_openrouter_key,
)

app = FastAPI(title="Journal Transcriber Local API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["*"],
)
catalog = Catalog()
audio_media = AudioMediaService(catalog)
workflow_store = WorkflowStore(catalog.db_path)
local_whisper = LocalWhisper(catalog)
pipeline_runner = PipelineRunner(workflow_store, local_whisper)


def _attach_word_alignments(outputs: list[dict]) -> list[dict]:
    """Attach saved Whisper scores to transcription outputs by their raw-version ID."""
    if not outputs:
        return outputs
    recording_id = outputs[0]["recording_id"]
    transcript_ids = [
        output["source_id"] for output in outputs
        if output["kind"] == "transcription" and output.get("source_id")
    ]
    alignments = workflow_store.get_transcript_word_alignments(recording_id, transcript_ids)
    for output in outputs:
        output["word_alignment"] = alignments.get(output.get("source_id")) if output["kind"] == "transcription" else None
    return outputs


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
    initial_output_name: str = "Transcription"
    steps: list[dict]


class PipelineRunRequest(BaseModel):
    """Recordings chosen for one single or batch workflow run."""
    recording_ids: list[str]


class OutputOrderRequest(BaseModel):
    """Move a named official output one position in the details panel."""
    direction: str


class OutputRenameRequest(BaseModel):
    """New visible name for one non-transcription official output."""
    name: str


class OutputRestoreRequest(BaseModel):
    """Optionally rename an archived output when its former name is occupied."""
    output_name: str | None = None


class OpenRouterKeyRequest(BaseModel):
    """An API key entered in Library settings; the secret is never returned."""
    api_key: str | None = Field(default=None, max_length=500)


class TranscriptionStart(BaseModel):
    """Select the transcription provider for one recording."""
    provider: str = "wsl-whisper"
    model: str = MODEL_ID


@app.get("/api/health")
def health() -> dict:
    """Expose a lightweight readiness check for the frontend."""
    return {"ok": True, "library_root": str(catalog.root)}


@app.get("/api/settings/openrouter")
def get_openrouter_settings() -> dict:
    """Report whether an OpenRouter key is available without exposing it."""
    key, source = openrouter_key()
    return {"configured": bool(key), "source": source}


@app.get("/api/openrouter/models")
def get_openrouter_models() -> list[dict]:
    """Return model names, publisher labels, and per-million-token prices."""
    try:
        return list_openrouter_models()
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.put("/api/settings/openrouter")
def put_openrouter_settings(request: OpenRouterKeyRequest) -> dict:
    """Save a key in the operating system credential store, never in SQLite."""
    secret = (request.api_key or "").strip()
    if not secret:
        raise HTTPException(status_code=422, detail="Enter an OpenRouter API key.")
    try:
        save_openrouter_key(secret)
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail="Could not save the key to Windows Credential Manager. Check that credential storage is available and try again.",
        ) from error
    return {"configured": True, "source": "Windows Credential Manager"}


@app.delete("/api/settings/openrouter")
def delete_openrouter_settings() -> dict:
    """Remove the saved key and report whether an environment fallback remains."""
    try:
        remove_openrouter_key()
    except Exception as error:
        raise HTTPException(status_code=503, detail="Could not remove the saved key from Windows Credential Manager.") from error
    key, source = openrouter_key()
    return {"configured": bool(key), "source": source}


@app.post("/api/settings/openrouter/test")
def test_openrouter_settings(request: OpenRouterKeyRequest) -> dict:
    """Test an unsaved key, or the configured key, without returning its value."""
    secret = request.api_key.strip() if request.api_key else None
    if not secret:
        secret, _ = openrouter_key()
    if not secret:
        raise HTTPException(status_code=400, detail="Enter or save an OpenRouter API key first.")
    return check_openrouter_key(secret)


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


@app.get("/api/recordings/{recording_id}/pipeline-runs")
def get_recording_pipeline_runs(recording_id: str) -> list[dict]:
    """List saved pipeline outputs for one recording, with the newest run first."""
    if not catalog.get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    return workflow_store.list_recording_run_outputs(recording_id)


@app.get("/api/recordings/{recording_id}/outputs")
def get_recording_outputs(recording_id: str) -> list[dict]:
    """List the one current official value for each named recording output."""
    if not catalog.get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    return _attach_word_alignments(workflow_store.list_official_outputs(recording_id))


@app.get("/api/recordings/{recording_id}/output-history")
def get_recording_output_history(recording_id: str) -> list[dict]:
    """List replaced and removed outputs that can be restored later."""
    if not catalog.get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    return _attach_word_alignments(workflow_store.list_output_history(recording_id))


@app.delete("/api/recordings/{recording_id}/outputs/{output_id}")
def archive_recording_output(recording_id: str, output_id: str) -> dict:
    """Remove an official output by moving its full value to previous versions."""
    archived = workflow_store.archive_official_output(recording_id, output_id)
    if not archived:
        raise HTTPException(status_code=404, detail="Official output not found")
    return archived


@app.patch("/api/recordings/{recording_id}/outputs/{output_id}/order")
def move_recording_output(recording_id: str, output_id: str, request: OutputOrderRequest) -> list[dict]:
    """Reorder non-transcription outputs; transcription remains pinned first."""
    try:
        result = workflow_store.move_official_output(recording_id, output_id, request.direction)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="Official output not found")
    return result


@app.patch("/api/recordings/{recording_id}/outputs/{output_id}/name")
def rename_recording_output(recording_id: str, output_id: str, request: OutputRenameRequest) -> dict:
    """Rename an official stage output while reserving Transcription for ASR."""
    try:
        result = workflow_store.rename_official_output(recording_id, output_id, request.name)
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if result is None:
        raise HTTPException(status_code=404, detail="Official output not found")
    return result


@app.post("/api/recordings/{recording_id}/output-history/{history_id}/restore")
def restore_recording_output(recording_id: str, history_id: str, request: OutputRestoreRequest) -> dict:
    """Restore archived content under its old name or a user-chosen free name."""
    try:
        return workflow_store.restore_output(recording_id, history_id, request.output_name)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except FileExistsError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/transcription/providers")
def get_transcription_providers(recording_id: str) -> list[dict]:
    """List local ASR choices with live device readiness and benchmark estimates."""
    recording = catalog.get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    return [local_whisper.provider_info(recording.get("duration_seconds"))]


@app.get("/api/transcription/models")
def get_transcription_models() -> list[dict]:
    """List supported local ASR model choices without starting a WSL probe."""
    return list_transcription_models()


@app.post("/api/recordings/{recording_id}/transcriptions")
def start_recording_transcription(recording_id: str, request: TranscriptionStart) -> dict:
    """Queue a local Whisper run and return its persistent ID for progress polling."""
    if request.provider != "wsl-whisper":
        raise HTTPException(status_code=422, detail="That transcription provider is not available.")
    try:
        return local_whisper.start(recording_id, request.model)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/recordings/{recording_id}/transcriptions/latest")
def get_latest_transcription(recording_id: str) -> dict | None:
    """Return the newest transcription run so its active timer can be restored."""
    if not catalog.get_recording(recording_id):
        raise HTTPException(status_code=404, detail="Recording not found")
    return catalog.latest_transcription_run(recording_id)


@app.get("/api/transcriptions/{run_id}")
def get_transcription_run(run_id: str) -> dict:
    """Return persistent state, elapsed time, and saved word-timed result for a run."""
    run = catalog.get_transcription_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Transcription run not found")
    return run


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
def get_pipeline_run(run_id: str, include_inputs: bool = False) -> dict:
    """Return all stage statuses, outputs, and errors for a batch run."""
    run = workflow_store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    if not include_inputs:
        run.pop("inputs", None)
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
    """Stream the unchanged source recording for playback and seeking in the review panel."""
    recording = catalog.get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    path = Path(recording["stored_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio file is missing from the library")
    return FileResponse(path, media_type=recording["mime_type"] or "application/octet-stream", filename=recording["original_name"], content_disposition_type="inline")


@app.get("/api/recordings/{recording_id}/audio/playback")
def get_browser_playback(recording_id: str) -> FileResponse:
    """Serve a cached MP3 rendition when the browser cannot decode the original format."""
    recording = catalog.get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    try:
        path = audio_media.browser_playback_path(recording)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return FileResponse(path, media_type="audio/mpeg", filename=f"{Path(recording['original_name']).stem}.mp3", content_disposition_type="inline")


@app.get("/api/recordings/{recording_id}/waveform")
def get_recording_waveform(recording_id: str) -> dict:
    """Return cached or freshly decoded amplitude peaks for the selected recording."""
    recording = catalog.get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found")
    try:
        return audio_media.waveform(recording)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


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
    possible_duplicate = catalog.get_recording(recording_id)
    recording = catalog.confirm_match(recording_id, canonical_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording or possible match not found")
    if possible_duplicate:
        audio_media.discard(possible_duplicate)
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
            recording = catalog.get_recording(recording_id)
            if catalog.move_to_trash(recording_id):
                deleted.append(recording_id)
                if recording:
                    audio_media.discard(recording)
            else:
                errors.append({"id": recording_id, "error": "Recording not found."})
        except OSError as error:
            errors.append({"id": recording_id, "error": str(error)})
    return {"deleted": deleted, "errors": errors}
