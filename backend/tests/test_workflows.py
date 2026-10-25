"""Tests for transcript versioning, pipeline validation, and reproducible run snapshots."""

import json
import sqlite3
from io import BytesIO

import pytest

from app.storage import Catalog
from app import model_catalog
from app.asr_catalog import DEFAULT_TRANSCRIPTION_MODEL_ID
from app.workflows import PipelineRunner, WorkflowStore, check_openrouter_key, openrouter_key, validate_pipeline


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


def test_raw_transcript_version_keeps_provider_and_model_metadata(tmp_path):
    """The ASR provider/model is stored beside the exact raw transcript version it produced."""
    catalog = Catalog(tmp_path / "library")
    recording, _, _ = catalog.import_file("fixture.mp3", BytesIO(b"fixture audio"), "audio/mpeg")
    store = WorkflowStore(catalog.db_path)

    saved = store.save_raw_transcript(recording["id"], "Whisper output", provider="wsl-whisper", model="openai/whisper-medium")
    restored = store.get_raw_transcripts(recording["id"])[0]

    assert saved["provider"] == restored["provider"] == "wsl-whisper"
    assert saved["model"] == restored["model"] == "openai/whisper-medium"


def test_word_alignment_probabilities_match_their_exact_raw_transcript_version(tmp_path):
    """Historical official transcripts retrieve only the Whisper scores from their own run."""
    catalog = Catalog(tmp_path / "library")
    recording, _, _ = catalog.import_file("fixture.mp3", BytesIO(b"fixture audio"), "audio/mpeg")
    store = WorkflowStore(catalog.db_path)
    first = store.save_raw_transcript(recording["id"], "Bonjour world", provider="wsl-whisper", model="openai/whisper-medium")
    second = store.save_raw_transcript(recording["id"], "A later transcript", provider="manual")
    run = catalog.create_transcription_run(recording["id"], "wsl-whisper", "openai/whisper-medium", "test GPU")
    catalog.finish_transcription_run(run["id"], "succeeded", result={
        "transcript_id": first["id"],
        "words": [
            {"start": 0.0, "end": 0.5, "text": "Bonjour"},
            {"start": 0.5, "end": 1.0, "text": " world"},
        ],
        "segments": [{"words": [
            {"start": 0.0, "end": 0.5, "word": "Bonjour", "probability": 0.91},
            {"start": 0.5, "end": 1.0, "word": " world", "probability": 0.42},
        ]}],
    })

    alignments = store.get_transcript_word_alignments(recording["id"], [first["id"], second["id"]])

    assert alignments[first["id"]]["words"][1]["probability"] == 0.42
    assert alignments[first["id"]]["words"][0]["text"] + alignments[first["id"]]["words"][1]["text"] == first["content"]
    assert second["id"] not in alignments


def test_saved_openrouter_key_precedes_environment_fallback(monkeypatch):
    """A key in system credential storage takes precedence over development env."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")
    monkeypatch.setattr("app.workflows.keyring.get_password", lambda *_: "saved-secret")

    assert openrouter_key() == ("saved-secret", "Windows Credential Manager")


def test_openrouter_key_falls_back_to_environment(monkeypatch):
    """The environment remains available when no saved credential exists."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-secret")
    monkeypatch.setattr("app.workflows.keyring.get_password", lambda *_: None)

    assert openrouter_key() == ("environment-secret", "environment variable")


def test_openrouter_connection_uses_current_key_endpoint(monkeypatch):
    """Connection check sends the supplied key only as an authorization header."""
    captured = {}

    class SuccessfulResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_args): return False

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["authorization"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return SuccessfulResponse()

    monkeypatch.setattr("app.workflows.urllib.request.urlopen", fake_urlopen)

    assert check_openrouter_key("test-key")["valid"] is True
    assert captured == {"url": "https://openrouter.ai/api/v1/key", "authorization": "Bearer test-key", "timeout": 15}


def test_openrouter_model_catalog_normalizes_and_caches(monkeypatch):
    """The catalog exposes readable prices and fetches OpenRouter only once per process."""
    calls = []

    class CatalogResponse:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self):
            return b'{"data":[{"id":"example-labs/model-x","name":"Model X","created":123,"pricing":{"prompt":"0.000002","completion":"0.000004"}}]}'

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        return CatalogResponse()

    monkeypatch.setattr(model_catalog, "_cached_models", None)
    monkeypatch.setattr(model_catalog.urllib.request, "urlopen", fake_urlopen)

    first = model_catalog.list_openrouter_models()
    second = model_catalog.list_openrouter_models()

    assert first == [{"id": "example-labs/model-x", "name": "Model X", "publisher": "Example Labs", "created": 123, "input_cost_per_million": 2.0, "output_cost_per_million": 4.0}]
    assert second is first
    assert calls == [("https://openrouter.ai/api/v1/models?sort=newest", 30)]


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


def test_pipeline_normalizes_legacy_json_output_to_text():
    """Previously saved JSON preferences cannot change the app's text output mode."""
    config = {"name": "Text only", "steps": [
        {"id": "first", "name": "Clean", "model": "provider/model", "prompt": "Clean", "input_ref": "raw", "output_format": "json"},
    ]}
    assert validate_pipeline(config)["steps"][0]["output_format"] == "text"


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


def test_transcription_name_is_reserved_for_local_asr_output():
    """A cleanup stage cannot replace the official transcription that future text work needs."""
    with pytest.raises(ValueError, match="reserved output name"):
        validate_pipeline({"name": "Invalid name", "steps": [
            {"id": "clean", "name": "Transcription", "kind": "cleanup", "model": "provider/model", "prompt": "Clean", "input_ref": "raw"},
        ]})


def test_transcription_stage_is_unique_first_and_uses_supported_model():
    """Local transcription is accepted only once at the head of the pipeline."""
    transcription = {"id": "asr", "name": "Transcribe", "kind": "transcription",
                     "model": DEFAULT_TRANSCRIPTION_MODEL_ID, "prompt": "", "input_ref": "audio"}
    cleanup = {"id": "clean", "name": "Cleanup", "kind": "cleanup",
               "model": "provider/model", "prompt": "Clean", "input_ref": "raw"}

    normalized = validate_pipeline({"name": "Audio pipeline", "steps": [transcription, cleanup]})
    assert normalized["steps"][0]["kind"] == "transcription"
    assert normalized["steps"][0]["input_ref"] == "audio"

    with pytest.raises(ValueError, match="only one transcription"):
        validate_pipeline({"name": "Duplicate", "steps": [transcription, {**transcription, "id": "asr-2"}]})
    with pytest.raises(ValueError, match="first pipeline stage"):
        validate_pipeline({"name": "Out of order", "steps": [cleanup, transcription]})
    with pytest.raises(ValueError, match="supported local transcription model"):
        validate_pipeline({"name": "Unsupported", "steps": [{**transcription, "model": "unknown/model"}]})


def test_audio_pipeline_transcribes_then_passes_raw_output_to_text_stage(tmp_path, monkeypatch):
    """An audio-first run saves raw ASR text and binds it to later raw-input stages."""
    catalog = Catalog(tmp_path / "library")
    recording, _, _ = catalog.import_file("fixture.mp3", BytesIO(b"fixture audio"), "audio/mpeg")
    store = WorkflowStore(catalog.db_path)
    pipeline = store.save_pipeline({"name": "Transcribe and clean", "steps": [
        {"id": "asr", "name": "Transcribe", "kind": "transcription", "model": DEFAULT_TRANSCRIPTION_MODEL_ID, "prompt": "", "input_ref": "audio"},
        {"id": "clean", "name": "Cleanup", "kind": "cleanup", "model": "provider/model", "prompt": "Clean", "input_ref": "raw"},
    ]})
    runner = PipelineRunner(store)

    class FakeTranscriber:
        def transcribe_for_pipeline(self, recording_id, model_id):
            assert model_id == DEFAULT_TRANSCRIPTION_MODEL_ID
            transcript = store.save_raw_transcript(recording_id, "bonjour from the recording")
            return {"text": transcript["content"], "transcript_version": transcript["version"]}

    runner.transcriber = FakeTranscriber()
    received = []
    monkeypatch.setattr(PipelineRunner, "_call_openrouter", staticmethod(lambda _step, text: received.append(text) or f"cleaned:{text}"))
    run = store.create_run(pipeline["id"], [recording["id"]])

    assert run["inputs"][0]["raw_content"] == ""
    assert run["stages"][0]["provider"] == "local_asr"
    runner._execute(run["id"])

    completed = store.get_run(run["id"])
    assert completed["status"] == "succeeded"
    assert received == ["bonjour from the recording"]
    assert completed["inputs"][0]["raw_version"] == 1
    assert completed["inputs"][0]["raw_content"] == "bonjour from the recording"
    assert completed["stages"][1]["output_text"] == "cleaned:bonjour from the recording"
    assert [item["content"] for item in store.get_raw_transcripts(recording["id"])] == ["bonjour from the recording"]


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


def test_same_named_stage_output_replaces_official_and_archives_old_text(tmp_path, monkeypatch):
    """Every run publishes the current named result and moves its predecessor into history."""
    catalog = Catalog(tmp_path / "library")
    recording, _, _ = catalog.import_file("fixture.mp3", BytesIO(b"fixture audio"), "audio/mpeg")
    store = WorkflowStore(catalog.db_path)
    store.save_raw_transcript(recording["id"], "source text")
    pipeline = store.save_pipeline({"name": "Cleanup", "steps": [
        {"id": "clean", "name": "Cleanup", "kind": "cleanup", "model": "provider/model", "prompt": "Clean", "input_ref": "raw"},
    ]})
    runner = PipelineRunner(store)
    outputs = iter(["first cleaned version", "second cleaned version"])
    monkeypatch.setattr(PipelineRunner, "_call_openrouter", staticmethod(lambda _step, _text: next(outputs)))

    first_run = store.create_run(pipeline["id"], [recording["id"]])
    runner._execute(first_run["id"])
    second_run = store.create_run(pipeline["id"], [recording["id"]])
    runner._execute(second_run["id"])

    official = store.list_official_outputs(recording["id"])
    previous = store.list_output_history(recording["id"])
    cleanup = next(item for item in official if item["name"] == "Cleanup")
    assert cleanup["content"] == "second cleaned version"
    replaced = next(item for item in previous if item["name"] == "Cleanup")
    assert replaced["content"] == "first cleaned version"
    assert replaced["archive_reason"] == "replaced"


def test_official_stage_can_be_renamed_and_future_runs_keep_the_custom_name(tmp_path, monkeypatch):
    """A per-recording name edit survives later stage reruns and preserves replaced text."""
    catalog = Catalog(tmp_path / "library")
    recording, _, _ = catalog.import_file("fixture.mp3", BytesIO(b"fixture audio"), "audio/mpeg")
    store = WorkflowStore(catalog.db_path)
    store.save_raw_transcript(recording["id"], "source text")
    pipeline = store.save_pipeline({"name": "Cleanup", "steps": [
        {"id": "clean", "name": "Cleanup", "kind": "cleanup", "model": "provider/model", "prompt": "Clean", "input_ref": "raw"},
    ]})
    runner = PipelineRunner(store)
    results = iter(["first result", "second result"])
    monkeypatch.setattr(PipelineRunner, "_call_openrouter", staticmethod(lambda _step, _text: next(results)))

    first_run = store.create_run(pipeline["id"], [recording["id"]])
    runner._execute(first_run["id"])
    cleanup = next(item for item in store.list_official_outputs(recording["id"]) if item["name"] == "Cleanup")
    renamed = store.rename_official_output(recording["id"], cleanup["id"], "Polished")
    assert renamed["name"] == "Polished"
    assert renamed["content"] == "first result"

    second_run = store.create_run(pipeline["id"], [recording["id"]])
    runner._execute(second_run["id"])
    official = store.list_official_outputs(recording["id"])
    history = store.list_output_history(recording["id"])
    assert [item["name"] for item in official if item["kind"] != "transcription"] == ["Polished"]
    assert next(item for item in official if item["name"] == "Polished")["content"] == "second result"
    assert next(item for item in history if item["name"] == "Polished")["content"] == "first result"


def test_official_output_rename_rejects_duplicates_and_transcription(tmp_path):
    """Names are unique per recording and the official ASR output stays immutable by name."""
    catalog = Catalog(tmp_path / "library")
    recording, _, _ = catalog.import_file("fixture.mp3", BytesIO(b"fixture audio"), "audio/mpeg")
    store = WorkflowStore(catalog.db_path)
    store.save_raw_transcript(recording["id"], "transcript")
    with store.connect() as db:
        store._publish_output(db, {"recording_id": recording["id"], "name": "Cleanup", "kind": "cleanup",
            "content": "cleaned", "provider": "openrouter", "model": "provider/model", "created_at": "2026-01-01T00:00:00+00:00"})
        store._publish_output(db, {"recording_id": recording["id"], "name": "Summary", "kind": "summary",
            "content": "summary", "provider": "openrouter", "model": "provider/model", "created_at": "2026-01-02T00:00:00+00:00"})

    outputs = store.list_official_outputs(recording["id"])
    cleanup = next(item for item in outputs if item["name"] == "Cleanup")
    transcription = next(item for item in outputs if item["kind"] == "transcription")
    with pytest.raises(FileExistsError, match="This stage name is already used for this recording"):
        store.rename_official_output(recording["id"], cleanup["id"], "summary")
    with pytest.raises(ValueError, match="reserved"):
        store.rename_official_output(recording["id"], cleanup["id"], "Transcription")
    with pytest.raises(ValueError, match="cannot be renamed"):
        store.rename_official_output(recording["id"], transcription["id"], "Words")


def test_archive_restore_conflict_requires_a_new_name_and_transcription_stays_first(tmp_path):
    """Removed outputs stay inspectable, conflicts cannot overwrite, and order keeps ASR pinned."""
    catalog = Catalog(tmp_path / "library")
    recording, _, _ = catalog.import_file("fixture.mp3", BytesIO(b"fixture audio"), "audio/mpeg")
    store = WorkflowStore(catalog.db_path)
    transcript = store.save_raw_transcript(recording["id"], "bonjour")
    with store.connect() as db:
        store._publish_output(db, {"recording_id": recording["id"], "name": "Cleaned", "kind": "cleanup",
            "content": "bonjour, cleaned", "provider": "openrouter", "model": "provider/model", "created_at": "2026-01-01T00:00:00+00:00"})
        store._publish_output(db, {"recording_id": recording["id"], "name": "Summary", "kind": "summary",
            "content": "A short summary", "provider": "openrouter", "model": "provider/model", "created_at": "2026-01-02T00:00:00+00:00"})

    official = store.list_official_outputs(recording["id"])
    summary = next(item for item in official if item["name"] == "Summary")
    store.move_official_output(recording["id"], summary["id"], "up")
    reordered = store.list_official_outputs(recording["id"])
    assert reordered[0]["kind"] == "transcription"
    assert [item["name"] for item in reordered[1:]] == ["Summary", "Cleaned"]

    cleaned = next(item for item in reordered if item["name"] == "Cleaned")
    archived = store.archive_official_output(recording["id"], cleaned["id"])
    assert archived["archive_reason"] == "removed"
    with store.connect() as db:
        store._publish_output(db, {"recording_id": recording["id"], "name": "Cleaned", "kind": "cleanup",
            "content": "new official cleaned text", "provider": "openrouter", "model": "provider/model", "created_at": "2026-01-03T00:00:00+00:00"})
    with pytest.raises(FileExistsError, match="Choose a different name"):
        store.restore_output(recording["id"], archived["id"])
    restored = store.restore_output(recording["id"], archived["id"], "Cleaned restored")
    assert restored["content"] == "bonjour, cleaned"
    assert restored["name"] == "Cleaned restored"
    assert transcript["content"] == "bonjour"


def test_text_pipeline_can_start_from_an_official_cleaning_output(tmp_path, monkeypatch):
    """Runs freeze the selected official output while still requiring an official transcript."""
    catalog = Catalog(tmp_path / "library")
    recording, _, _ = catalog.import_file("fixture.mp3", BytesIO(b"fixture audio"), "audio/mpeg")
    store = WorkflowStore(catalog.db_path)
    store.save_raw_transcript(recording["id"], "raw version")
    with store.connect() as db:
        store._publish_output(db, {"recording_id": recording["id"], "name": "Cleanup", "kind": "cleanup",
            "content": "official cleaned text", "provider": "openrouter", "model": "provider/clean", "created_at": "2026-01-01T00:00:00+00:00"})
    pipeline = store.save_pipeline({"name": "Summarize cleaned", "initial_output_name": "Cleanup", "steps": [
        {"id": "summary", "name": "Summary", "kind": "summary", "model": "provider/model", "prompt": "Summarize", "input_ref": "raw"},
    ]})
    runner = PipelineRunner(store)
    run = store.create_run(pipeline["id"], [recording["id"]])
    assert run["inputs"][0]["raw_content"] == "official cleaned text"
    assert run["inputs"][0]["source_output_name"] == "Cleanup"

    received = []
    monkeypatch.setattr(PipelineRunner, "_call_openrouter", staticmethod(lambda _step, text: received.append(text) or "summary"))
    runner._execute(run["id"])
    assert received == ["official cleaned text"]

    transcription = next(item for item in store.list_official_outputs(recording["id"]) if item["kind"] == "transcription")
    store.archive_official_output(recording["id"], transcription["id"])
    with pytest.raises(ValueError, match="no official transcription"):
        store.create_run(pipeline["id"], [recording["id"]])


def test_existing_run_and_transcript_data_is_backfilled_into_official_and_previous_outputs(tmp_path):
    """Opening an older library keeps its newest outputs official and moves earlier values to history."""
    catalog = Catalog(tmp_path / "library")
    recording, _, _ = catalog.import_file("fixture.mp3", BytesIO(b"fixture audio"), "audio/mpeg")
    db = sqlite3.connect(catalog.db_path)
    db.executescript("""
        CREATE TABLE raw_transcripts(id TEXT PRIMARY KEY,recording_id TEXT,version INTEGER,content TEXT,created_at TEXT,UNIQUE(recording_id,version));
        CREATE TABLE pipelines(id TEXT PRIMARY KEY,name TEXT,description TEXT,config_json TEXT,version INTEGER,created_at TEXT,updated_at TEXT);
        CREATE TABLE pipeline_runs(id TEXT PRIMARY KEY,pipeline_id TEXT,pipeline_name TEXT,snapshot_json TEXT,status TEXT,created_at TEXT,started_at TEXT,finished_at TEXT,error TEXT);
        CREATE TABLE run_inputs(run_id TEXT,recording_id TEXT,raw_version INTEGER,raw_content TEXT,PRIMARY KEY(run_id,recording_id));
        CREATE TABLE stage_runs(id TEXT PRIMARY KEY,run_id TEXT,recording_id TEXT,step_id TEXT,step_index INTEGER,step_name TEXT,provider TEXT,model TEXT,prompt TEXT,prompt_hash TEXT,input_ref TEXT,output_format TEXT,status TEXT,input_text TEXT,output_text TEXT,error TEXT,started_at TEXT,finished_at TEXT,UNIQUE(run_id,recording_id,step_id));
    """)
    db.executemany("INSERT INTO raw_transcripts VALUES(?,?,?,?,?)", [
        ("transcript-v1", recording["id"], 1, "raw one", "2026-01-01T00:00:00+00:00"),
        ("transcript-v2", recording["id"], 2, "raw two", "2026-01-02T00:00:00+00:00"),
    ])
    db.execute(
        "INSERT INTO transcription_runs(id,recording_id,provider,model,device,status,started_at,finished_at,result_json) VALUES(?,?,?,?,?,?,?,?,?)",
        ("asr-run", recording["id"], "wsl-whisper", "openai/whisper-medium", "AMD Radeon RX 9060 XT", "succeeded",
         "2026-01-02T00:00:00+00:00", "2026-01-02T00:00:01+00:00",
         json.dumps({"transcript_id": "transcript-v2", "transcript_version": 2})),
    )
    snapshot = json.dumps({"steps": [{"id": "clean", "kind": "cleanup"}]})
    for index, (output, timestamp) in enumerate([
        ("cleaned one", "2026-01-03T00:00:00+00:00"),
        ("cleaned two", "2026-01-04T00:00:00+00:00"),
    ]):
        run_id = f"run-{index}"
        db.execute("INSERT INTO pipeline_runs VALUES(?,?,?,?,?,?,?,?,?)",
                   (run_id, "pipeline", "Cleanup", snapshot, "succeeded", timestamp, timestamp, timestamp, None))
        db.execute("INSERT INTO stage_runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (f"stage-{index}", run_id, recording["id"], "clean", 0, "Cleanup", "openrouter", "provider/model",
                    "Clean", "hash", "raw", "text", "succeeded", "raw", output, None, timestamp, timestamp))
    db.commit()
    db.close()

    store = WorkflowStore(catalog.db_path)
    official = store.list_official_outputs(recording["id"])
    history = store.list_output_history(recording["id"])

    official_transcript = next(item for item in official if item["kind"] == "transcription")
    assert official_transcript["content"] == "raw two"
    assert official_transcript["provider"] == "wsl-whisper"
    assert official_transcript["model"] == "openai/whisper-medium"
    assert next(item for item in official if item["name"] == "Cleanup")["content"] == "cleaned two"
    assert {item["content"] for item in history} == {"raw one", "cleaned one"}


def test_existing_output_provenance_is_enriched_after_initial_output_migration(tmp_path):
    """A follow-up migration recovers ASR details when the output list was already backfilled."""
    catalog = Catalog(tmp_path / "library")
    recording, _, _ = catalog.import_file("fixture.mp3", BytesIO(b"fixture audio"), "audio/mpeg")
    store = WorkflowStore(catalog.db_path)
    transcript = store.save_raw_transcript(recording["id"], "Prior Whisper text")
    with store.connect() as db:
        db.execute("UPDATE raw_transcripts SET provider='legacy transcript',model='' WHERE id=?", (transcript["id"],))
        db.execute("UPDATE official_outputs SET provider='legacy transcript',model='' WHERE source_id=?", (transcript["id"],))
        db.execute("DELETE FROM workflow_migrations WHERE name='transcription-output-provenance-v2'")
        db.execute(
            "INSERT INTO transcription_runs(id,recording_id,provider,model,device,status,started_at,finished_at,result_json) VALUES(?,?,?,?,?,?,?,?,?)",
            ("asr-run", recording["id"], "wsl-whisper", "openai/whisper-medium", "AMD Radeon RX 9060 XT", "succeeded",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:10+00:00",
             json.dumps({"transcript_id": transcript["id"], "transcript_version": transcript["version"]})),
        )

    migrated = WorkflowStore(catalog.db_path)
    raw = migrated.get_raw_transcripts(recording["id"])[0]
    official = next(item for item in migrated.list_official_outputs(recording["id"]) if item["kind"] == "transcription")
    assert (raw["provider"], raw["model"]) == ("wsl-whisper", "openai/whisper-medium")
    assert (official["provider"], official["model"], official["run_id"]) == ("wsl-whisper", "openai/whisper-medium", "asr-run")
