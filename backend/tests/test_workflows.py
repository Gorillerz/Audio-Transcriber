"""Tests for transcript versioning, pipeline validation, and reproducible run snapshots."""

from io import BytesIO

import pytest

from app.storage import Catalog
from app.workflows import PipelineRunner, WorkflowStore, validate_pipeline


def test_raw_transcript_saves_new_versions_without_overwriting(tmp_path):
    """Saving a correction appends a version and preserves the earlier source text."""
    catalog = Catalog(tmp_path / "library")
    recording, _, _ = catalog.import_file("fixture.mp3", BytesIO(b"fixture audio"), "audio/mpeg")
    store = WorkflowStore(catalog.db_path)

    first = store.save_raw_transcript(recording["id"], "First raw transcript")
    second = store.save_raw_transcript(recording["id"], "Corrected raw transcript")

    assert first["version"] == 1
    assert second["version"] == 2
    assert [item["content"] for item in store.get_raw_transcripts(recording["id"])] == ["Corrected raw transcript", "First raw transcript"]
    assert catalog.get_recording(recording["id"])["status_source"] == "derived"


def test_pipeline_binding_requires_raw_or_earlier_step_output():
    """Rejecting forward references prevents stale or cyclic stage inputs."""
    config = {"name": "Chain", "steps": [
        {"id": "first", "name": "Clean", "model": "provider/model", "prompt": "Clean", "input_ref": "raw"},
        {"id": "second", "name": "Title", "model": "provider/model", "prompt": "Title", "input_ref": "first"},
    ]}
    assert validate_pipeline(config)["steps"][1]["input_ref"] == "first"
    config["steps"][0]["input_ref"] = "second"
    with pytest.raises(ValueError, match="earlier step"):
        validate_pipeline(config)


def test_run_freezes_raw_text_and_pipeline_revision(tmp_path):
    """Later edits to a pipeline or raw transcript do not rewrite an existing run input."""
    catalog = Catalog(tmp_path / "library")
    recording, _, _ = catalog.import_file("fixture.mp3", BytesIO(b"fixture audio"), "audio/mpeg")
    store = WorkflowStore(catalog.db_path)
    store.save_raw_transcript(recording["id"], "Raw v1")
    config = {"name": "Cleanup", "steps": [
        {"id": "clean", "name": "Clean", "model": "provider/model", "prompt": "Clean this", "input_ref": "raw", "output_format": "text"},
    ]}
    pipeline = store.save_pipeline(config)
    run = store.create_run(pipeline["id"], [recording["id"]])
    config["steps"][0]["prompt"] = "A later instruction"
    store.save_pipeline(config, pipeline["id"])
    store.save_raw_transcript(recording["id"], "Raw v2")

    frozen_run = store.get_run(run["id"])
    frozen_input = store.run_inputs(run["id"])[0]
    assert frozen_run["pipeline_snapshot"]["steps"][0]["prompt"] == "Clean this"
    assert frozen_run["pipeline_snapshot"]["pipeline_version"] == 1
    assert frozen_input["raw_version"] == 1
    assert frozen_input["raw_content"] == "Raw v1"


def test_pipeline_rejects_missing_model_or_prompt():
    """Every provider stage must carry an explicit model and prompt before saving."""
    with pytest.raises(ValueError, match="model ID"):
        validate_pipeline({"name": "Invalid", "steps": [{"id": "a", "name": "Step", "prompt": "Run", "input_ref": "raw"}]})


def test_failed_stage_retry_keeps_successful_output_and_binds_downstream_input(tmp_path, monkeypatch):
    """Retry skips completed work and passes the selected prior stage output onward."""
    catalog = Catalog(tmp_path / "library")
    recording, _, _ = catalog.import_file("fixture.mp3", BytesIO(b"fixture audio"), "audio/mpeg")
    store = WorkflowStore(catalog.db_path)
    store.save_raw_transcript(recording["id"], "source text")
    pipeline = store.save_pipeline({"name": "Retry demo", "steps": [
        {"id": "clean", "name": "Clean", "model": "provider/clean", "prompt": "clean", "input_ref": "raw"},
        {"id": "summary", "name": "Summary", "model": "provider/summary", "prompt": "summarize", "input_ref": "clean"},
    ]})
    runner = PipelineRunner(store)
    run = store.create_run(pipeline["id"], [recording["id"]])
    fail_summary = True
    received = []

    def fake_call(step, input_text):
        nonlocal fail_summary
        received.append((step["id"], input_text))
        if step["id"] == "summary" and fail_summary:
            raise RuntimeError("temporary provider error")
        return f"output:{input_text}"

    monkeypatch.setattr(PipelineRunner, "_call_openrouter", staticmethod(fake_call))
    runner._execute(run["id"])
    first = store.get_run(run["id"])
    assert first["status"] == "failed"
    assert first["stages"][0]["output_text"] == "output:source text"

    fail_summary = False
    store.retry_run(run["id"])
    runner._execute(run["id"])
    final = store.get_run(run["id"])
    assert final["status"] == "succeeded"
    assert received == [("clean", "source text"), ("summary", "output:source text"), ("summary", "output:source text")]
    assert final["stages"][0]["output_text"] == "output:source text"
