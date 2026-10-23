# Architecture

## Initial direction

Build a single-user local web app: React + TypeScript for the review interface, FastAPI + Python for the local API and media pipeline, and SQLite for the catalog, processing history, and persistent job queue. The app runs on localhost and reads files from a user-selected library folder. This keeps audio local unless the user invokes a transcription or model stage that sends it to a provider.

Keep transcription providers behind a small adapter interface. Keep text-model stages behind a separate OpenRouter adapter. Provider model IDs and capabilities are configuration, not assumptions embedded in the UI. The UI should show whether a provider supplies word timestamps, segment timestamps, or no timing.

Implement in small vertical slices from `MVP_PLAN.md`. MVP1 should establish the library interface and import/catalog behavior. MVP2 should exercise a configurable pipeline against saved or fixture raw transcripts. MVP3 should add a real ASR provider and timed audio review. This order lets the pipeline and UI be adjusted before depending on a transcription service.

## Library layout

```text
JournalLibrary/
  Inbox/                 # files dropped here for discovery
  Audio/<recording-id>/   # app-managed source audio
  Transcripts/<recording-id>.json
  Exports/<recording-id>.txt
  app.sqlite
```

Importing from the UI or inbox copies the source into the managed library by default. Preserve its original filename and filesystem metadata in the catalog. Do not move or rename the user's source during import. A future setting may allow an external folder to be indexed without copying.

## Identity and status

- Give each recording an immutable UUID.
- Calculate SHA-256 on import. An exact hash match identifies the same bytes even after a filename change.
- Store size, duration, media metadata, and timestamps as supporting evidence. If the hash differs but metadata is similar, show a possible duplicate for user confirmation; metadata alone is not a definitive identity key.
- Store status and history in SQLite: discovered, queued, transcribing, transcribed, processing, ready, failed, or needs review. Treat these as derived workflow state, not folder names.

## Data model

- `recording`: UUID, stored path, original name, content hash, size, duration, media metadata, group, and timestamps.
- `transcription_run`: recording UUID, provider, model, configuration, start/end time, status, and error details.
- `transcript_version`: recording UUID, version type (raw, edited, cleaned), schema version, content, and provenance.
- `processing_run`: stage, provider/model, prompt version, input version, output version, status, and error details.
- `job`: durable queue item, retry count, progress, and timestamps.

Store raw word/segment timing as structured data. Keep edited text as a new version. When edits change wording, retain the original alignment and indicate that the edited wording may not match the original word timing exactly.

## Processing flow

1. Discover and validate an audio file; copy it to managed storage and calculate its hash and media metadata.
2. Add it to the catalog and queue a transcription job when requested.
3. A persistent worker claims queued jobs, writes progress/errors to SQLite, and saves the provider's original structured response.
4. Run selected text stages after transcription. Each stage consumes a named transcript version and stores a new version with provider, model, prompt version, and output.
5. Export the current human-readable transcript and structured JSON. Exports can be regenerated from catalog state.

Use a persistent database-backed worker rather than an in-memory web request task so app restarts do not lose queued work. Start with one worker; parallelism can be added after rate limits and local resource use are understood.

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
