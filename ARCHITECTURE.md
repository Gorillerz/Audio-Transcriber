# Architecture

## Initial direction

Build a single-user local web app: React + TypeScript for the review interface, FastAPI + Python for the local API and media pipeline, and SQLite for the catalog, processing history, and persistent job queue. The app runs on localhost and reads files from a user-selected library folder. This keeps audio local unless the user invokes a transcription or model stage that sends it to a provider.

Keep transcription providers behind a small adapter interface. Keep text-model stages behind a separate OpenRouter adapter. Provider model IDs and capabilities are configuration, not assumptions embedded in the UI. The UI should show whether a provider supplies word timestamps, segment timestamps, or no timing.

Implement in small vertical slices from `MVP_PLAN.md`. MVP1 should establish the library interface and import/catalog behavior. MVP2 should exercise a configurable pipeline against saved or fixture raw transcripts. MVP3 should add a real ASR provider and timed audio review. This order lets the pipeline and UI be adjusted before depending on a transcription service.

## Library layout

```text
%LOCALAPPDATA%/JournalTranscriber/Library/  # default on Windows; configurable with JOURNAL_LIBRARY_DIR
  Audio/<recording-id>/<original-name>       # app-managed source audio
  app.sqlite                                  # recording catalog and aliases
```

Future milestones can add `Inbox/`, `Transcripts/`, and `Exports/` as those workflows are implemented.

Importing from the UI copies the source into the managed library by default. Preserve its original filename and available embedded recording date in the catalog. The filesystem modification time is not treated as the recording date; show an unknown-date fallback when the audio has no embedded date. Mutagen reads common media metadata, with a format-specific MP3 parser fallback for files that generic detection sees only as ID3 tags. Do not move or rename the user's source during import. A future setting may allow an external folder to be indexed without copying.

The FastAPI service listens on loopback for the local React UI. It exposes health, catalog, import, audio-file, metadata-match confirmation, manual status, recording-group, transcript-version, pipeline-definition, and pipeline-run routes. Transcription status can be marked manually for legacy recordings until transcript data is linked.

Confirmed recording deletion calls Send2Trash to move the managed audio file into the operating system's trash, then removes its catalog row and group memberships from SQLite. A failed trash operation leaves the catalog entry in place.

## Identity and status

- Give each recording an immutable UUID.
- Store user-created groups in SQLite (`recording_groups`) and memberships in a many-to-many join table (`group_recordings`), allowing one recording to appear in more than one group.
- Calculate SHA-256 on import. An exact hash match identifies the same bytes even after a filename change.
- Store size, duration, media metadata, and timestamps as supporting evidence. If the hash differs but metadata is similar, show a possible duplicate for user confirmation; metadata alone is not a definitive identity key.
- Store status and history in SQLite: discovered, queued, transcribing, transcribed, processing, ready, failed, or needs review. Treat these as derived workflow state, not folder names.
- In MVP1, allow a manual status source for legacy recordings whose transcript file is not imported yet; display that distinction in the details panel. Once transcript data is linked, actual transcript records become the source of derived status.

## Data model

- `recording`: UUID, stored path, original name, content hash, size, duration, media metadata, and timestamps.
- `recording_group` and `group_recording`: named groups and their many-to-many recording memberships.
- `raw_transcripts`: append-only plain-text transcript versions associated with a recording.
- `pipelines`: the current editable pipeline definition and revision number.
- `pipeline_runs`: immutable pipeline configuration snapshot and batch state.
- `run_inputs`: frozen raw text/version used by each recording in a run.
- `stage_runs`: per-recording stage status, input reference and text, output, provider/model, prompt and prompt hash, timestamps, and error.
- `transcription_run`: recording UUID, provider, model, configuration, start/end time, status, and error details.
- `transcript_version`: recording UUID, version type (raw, edited, cleaned), schema version, content, and provenance.
- `processing_run`: stage, provider/model, prompt version, input version, output version, status, and error details.
- `job`: durable queue item, retry count, progress, and timestamps.

Store raw word/segment timing as structured data. Keep edited text as a new version. When edits change wording, retain the original alignment and indicate that the edited wording may not match the original word timing exactly.

## Processing flow

1. Discover and validate an audio file; copy it to managed storage and calculate its hash and media metadata.
2. Add it to the catalog. Real audio transcription is implemented in MVP3.
3. In MVP2, save existing or fixture raw text as an append-only transcript version.
4. Snapshot the chosen pipeline configuration and current raw input into SQLite, then queue its ordered stages on one background worker.
5. Each stage uses either the frozen raw text or an explicitly selected earlier stage output. OpenRouter receives transcript text only when the user launches the pipeline.
6. Save stage input/output and provider/model/prompt provenance in SQLite. Retrying a failed run skips stages already marked successful.
7. Human-readable and structured transcript exports are planned after transcript workflows are reviewed.

Use a persistent database-backed worker rather than an in-memory web request task so app restarts do not lose queued work. MVP2 recovers queued or interrupted runs when the service starts and uses one worker; parallelism can be added after rate limits and local resource use are understood. The OpenRouter key is read from `OPENROUTER_API_KEY` in the API process environment and is never stored in the app database.

## Transcript playback

Normalize provider results into a common internal shape with segments and optional words, each with start/end seconds and text. The review screen uses those times to seek and play the source. Keep source audio immutable. If a provider has no word timing, allow segment-level playback and label that limitation.

The transcript editor should save changes as a new edited version. Retain the raw provider response and raw transcript. Edits that change word count or wording must not silently invent new alignment; preserve the source timing and mark edited timing as needing review when the correspondence is uncertain.

## Secrets and privacy

- Keep provider keys out of the database, transcript files, logs, and source control.
- Use the operating system credential store for saved keys when available; use environment variables only for development.
- Show which provider receives audio or transcript text before the first run and in the run history.
- Never send audio to OpenRouter for text-only cleanup; send only the selected transcript version to the chosen text model.

## Agent-maintained documents

- `PRODUCT_SPEC.md`: user-visible behavior and acceptance checks.
- `ARCHITECTURE.md`: components, data ownership, storage, and important technical decisions.
- `AGENTS.md`: short instructions for coding agents and links to the two documents above.
- `MVP_PLAN.md` and `docs/mvp/`: ordered scope, acceptance criteria, and checklists for each milestone.
- `TESTING.md`: shared expectations for automated checks and user-run verification.
- Prompt templates: versioned separately as application data or files under `prompts/`; keep them editable in the app and record the exact version used for each run.

Update the product spec when behavior or acceptance criteria change. Update this document when storage, data flow, or technology decisions change. Keep agent instructions short and procedural; do not copy the full product spec into them.
