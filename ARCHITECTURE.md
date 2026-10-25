# Architecture

## Initial direction

Build a single-user local web app: React + TypeScript for the review interface, FastAPI + Python for the local API and media pipeline, and SQLite for the catalog, processing history, and persisted job state. The app runs on localhost and reads files from a configured library folder. This keeps audio local unless the user invokes a transcription or model stage that sends it to a provider.

Keep transcription providers behind a small adapter interface. Keep text-model stages behind a separate OpenRouter adapter. Provider model IDs and capabilities are configuration, not assumptions embedded in the UI. The UI should show whether a provider supplies word timestamps, segment timestamps, or no timing.

On browser app load, request OpenRouter's public model catalog through the local API using its newest-first sort. The backend normalizes model ID, name, publisher label, creation time, and input/output USD price per million tokens, then caches the result for its process lifetime. Pipeline stage selectors filter the cached list locally while retaining newest-first order; the chosen model ID remains the value stored in pipeline definitions. If the catalog request fails, users can still enter a model ID manually.

Implement in small vertical slices from `MVP_PLAN.md`. MVP1 establishes the library interface and import/catalog behavior. MVP2 exercises configurable text pipelines against saved or fixture raw transcripts. MVP3 adds the real ASR provider and timed audio review; an optional local transcription stage can now precede text stages in a pipeline.

## Library layout

Resolve the library root from a Git-ignored project-local `.journal-library-root` file first, then `JOURNAL_LIBRARY_DIR`, then `%LOCALAPPDATA%/JournalTranscriber/Library` on Windows (or the XDG data directory on Linux). The pin file stores a relative path so it follows the checkout if the project directory moves. If the pinned directory lacks its catalog or `Audio` directory, fail startup with a clear error; do not silently initialize a second empty catalog. Keep this machine-specific file out of version control.

```text
.journal-library-root                      # local-only path pin, when configured
%LOCALAPPDATA%/JournalTranscriber/Library/  # Windows fallback when no pin or environment override exists
  Audio/<recording-id>/<original-name>       # app-managed source audio
  Cache/Waveforms/<sha256>.json               # regenerable 20 Hz amplitude envelopes
  Cache/Playback/<sha256>.mp3                 # regenerable browser-compatible renditions
  app.sqlite                                  # recording catalog and aliases
```

Future milestones can add `Inbox/`, `Transcripts/`, and `Exports/` as those workflows are implemented.

Importing from the UI copies the source into the managed library by default. Preserve its original filename and available embedded recording date in the catalog. The filesystem modification time is not treated as the recording date; show an unknown-date fallback when the audio has no embedded date. Mutagen reads common media metadata, with a format-specific MP3 parser fallback for files that generic detection sees only as ID3 tags. Do not move or rename the user's source during import. A future setting may allow an external folder to be indexed without copying.

On startup, reconcile stale absolute `stored_path` values against `Audio/<recording-id>/` in the active root. Update a path only when a file in that recording's managed folder has the same SHA-256 as the catalog entry; never move or rewrite audio during this repair. This handles library-root layout changes while refusing to bind a different file to the recording.

The FastAPI service listens on loopback for the local React UI. It exposes health, catalog, import, source-audio and browser-playback audio, cached waveform, metadata-match confirmation, manual status, recording-group, raw-transcript history, official-output naming/order/archive, pipeline-definition/run, and transcription-provider/model/job routes. Official and historical output responses attach Whisper word alignment by raw transcript ID; the details panel uses it only when those timed words reconstruct the exact transcript text. Run-stage records remain as execution provenance and retry state. Transcription status can be marked manually for legacy recordings until transcript data is linked.

`AudioMediaService` derives playback and visualization media from the immutable source. The waveform endpoint decodes to mono 8 kHz PCM with FFmpeg and stores normalized 20 Hz peak values in `Cache/Waveforms`, keyed by source SHA-256. The browser first requests original audio; when its native decoder cannot play the source, it requests a quality MP3 in `Cache/Playback`. These caches are disposable derivatives; the catalog hash keeps cache identity stable across filename changes. FFmpeg is only required to build waveform data or a fallback MP3. Native playback continues without it. `JOURNAL_FFMPEG_PATH` can identify a specific executable when it is not on PATH.

The initial local ASR adapter runs OpenAI Whisper medium with word timestamps inside WSL, keeping provider-specific logic out of the UI. It probes PyTorch and the Whisper package in `Ubuntu-24.04` and reports the detected GPU before launch. `JOURNAL_WSL_DISTRO` and `JOURNAL_WSL_PYTHON` can override the defaults (`Ubuntu-24.04` and `$HOME/.venvs/rocm-asr-probe/bin/python`). Windows audio and worker paths are mapped to WSL drive mounts. The warm estimate uses the 60-second RX 9060 XT benchmark (19.45 seconds inference per minute of audio plus 12.1 seconds startup); it is explicitly approximate and does not include a first-time model download.

The pipeline workflow UI has separate **Pipeline** and **Run** tabs, with the saved-pipeline and recent-run sidebar kept visible on both. Pipeline contains the stage editor. Run places the selected or active batch queue beside the execution flow; the queue derives each recording's ready, queued, processing, completed, or failed state from the persisted run and stage records. Selecting a queue item focuses the flow on its outputs, while the current in-progress item is tracked separately so manual inspection does not hide run progress.

Confirmed recording deletion calls Send2Trash to move the managed audio file into the operating system's trash, then removes its catalog row and group memberships from SQLite. A failed trash operation leaves the catalog entry in place.

## Identity and status

- Give each recording an immutable UUID.
- Store user-created groups in SQLite (`recording_groups`) and memberships in a many-to-many join table (`group_recordings`), allowing one recording to appear in more than one group.
- Calculate SHA-256 on import. An exact hash match identifies the same bytes even after a filename change.
- Store size, duration, media metadata, and timestamps as supporting evidence. If the hash differs but metadata is similar, show a possible duplicate for user confirmation; metadata alone is not a definitive identity key.
- MVP1 stores `untranscribed`/`transcribed` catalog status and whether it is manual or transcript-derived. MVP2 separately stores queued/running/succeeded/failed pipeline and stage states. Future transcription states should be derived from persisted transcription jobs rather than encoded in folders.
- In MVP1, allow a manual status source for legacy recordings whose transcript file is not imported yet; display that distinction in the details panel. Once transcript data is linked, actual transcript records become the source of derived status.

## Data model

- `recording`: UUID, stored path, original name, content hash, size, duration, media metadata, and timestamps.
- `recording_group` and `group_recording`: named groups and their many-to-many recording memberships.
- `raw_transcripts`: append-only transcript versions associated with a recording, with the provider and model stored on each version. Successful ASR-run IDs are linked through the run result's transcript ID/version.
- `official_outputs`: one current output per case-insensitive `(recording_id, name)`, with type, exact text, provider/model, source run/stage, creation time, and display order. Transcription outputs are pinned first; non-transcription outputs use their saved order.
- `output_history`: full copies of replaced and removed official outputs, including their stage, provenance, original execution time, archive time, and reason. Restoring copies the archived value into the official table and keeps the history entry intact; a name collision requires a new name.
- `output_name_overrides`: per-recording names chosen for a pipeline step. Renaming a non-transcription official output updates its display name and records this override so later runs of the same step continue to publish under the user's chosen name. The ASR Transcription name is reserved.
- `pipelines`: the current editable pipeline definition and revision number.
- `pipeline_runs`: immutable pipeline configuration snapshot and batch state.
- `run_inputs`: frozen exact text, selected official output ID/name, and raw transcript version where applicable. A pipeline starting with local transcription initializes this snapshot from audio, then fills it with the new raw and official transcription after ASR completes.
- `stage_runs`: per-recording stage status, input reference and text, output, provider/model, prompt and prompt hash, timestamps, and error. The provider is `local_asr` for a transcription stage and `openrouter` for text stages.
- `transcription_runs`: provider/model/device, start/end time, status, error, and the raw Whisper response including normalized word timings and per-word probabilities. Its result records the transcript ID/version, allowing old transcript versions and official/history outputs to recover the exact alignment that created them. Extracted text is appended to `raw_transcripts` and published in `official_outputs`; pipelines consume the selected official value.
- Planned follow-up for MVP3: structured edited transcript versions with timing provenance, batch scheduling, cancellation, and a durable worker queue with retries.

Store raw word/segment timing as structured data. Keep edited text as a new version. When edits change wording, retain the original alignment and indicate that the edited wording may not match the original word timing exactly.

## Processing flow

1. Discover and validate an audio file; copy it to managed storage and calculate its hash and media metadata.
2. Add it to the catalog. The MVP3 local Whisper adapter runs in WSL and stores the raw provider result and a text history version.
3. In MVP2, save existing or fixture raw text as an append-only transcript version.
4. For text-only pipelines, validate that every recording has an official transcription and the configured starting output. Snapshot that exact output's text and identity into SQLite before queueing the stages. A local transcription stage may instead start from audio without an existing transcript.
5. A first local-ASR stage sends selected audio to the configured WSL Whisper worker, appends text to immutable raw history, and publishes it as the current official **Transcription** output. Later stages use that new text or an explicitly selected earlier stage output. OpenRouter receives only the chosen text input.
6. Atomically save each successful text stage's output and publish it under the stage name. If that name already has an official output, copy the old value to `output_history` before promoting the new one. Retrying a failed run skips successful stages.
7. The recording details panel reads named official outputs and the collapsed previous-version archive. The Run tab continues to show active/recent execution records and stage flow. Local simulations are a UI-only pass-through preview and are not stored in SQLite.
8. Human-readable and structured transcript exports are planned after transcript review is implemented.

The current ASR slice allows one local run at a time in a backend worker thread. Run state and outputs are persisted in SQLite, and an active run is marked failed/retryable if the API restarts. This makes status and results recoverable but does not yet provide a durable queue or restart/resume of the model process.

Use a persistent database-backed worker rather than an in-memory web request task so app restarts do not lose queued work. MVP2 recovers queued or interrupted runs when the service starts and uses one worker; parallelism can be added after rate limits and local resource use are understood. The OpenRouter key can be entered in Library settings and is stored using the operating system credential provider through Python Keyring (Windows Credential Manager on Windows). It is never stored in the app database or returned to the UI after save. The backend falls back to `OPENROUTER_API_KEY` when no saved key exists; a saved key takes precedence.

## Transcript playback

The Recording Details panel serves the original file through FastAPI for native browser playback and HTTP range seeking. It offers play/pause, five-second back/forward, speeds from 1× through 2×, and a seekable canvas waveform. The waveform is a compact audio-level envelope, not voice activity detection: it can show loudness and pauses but cannot prove which sections contain speech. Clicking an aligned timed word seeks to its start and starts playback; the current timed word is highlighted during playback. Audio and waveform data are keyed to the recording ID/hash, and the media service never edits source audio. If a provider has segment rather than word timing, seeking can be offered at segment granularity.

The transcript editor should save changes as a new edited version. Retain the raw provider response and raw transcript. Edits that change word count or wording must not silently invent new alignment; preserve the source timing and mark edited timing as needing review when the correspondence is uncertain.

## Secrets and privacy

- Keep provider keys out of the database, transcript files, logs, and source control.
- Use the operating system credential store for saved keys when available; use environment variables only for development.
- Show which provider receives audio or transcript text before the first run and in the run history.
- Never send audio to OpenRouter for text-only cleanup; send only the selected official output text to the chosen text model.

## Agent-maintained documents

- `PRODUCT_SPEC.md`: user-visible behavior and acceptance checks.
- `ARCHITECTURE.md`: components, data ownership, storage, and important technical decisions.
- `AGENTS.md`: short instructions for coding agents and links to the two documents above.
- `MVP_PLAN.md` and `docs/mvp/`: ordered scope, acceptance criteria, and checklists for each milestone.
- `TESTING.md`: shared expectations for automated checks and user-run verification.
- Prompt templates: versioned separately as application data or files under `prompts/`; keep them editable in the app and record the exact version used for each run.

Update the product spec when behavior or acceptance criteria change. Update this document when storage, data flow, or technology decisions change. Keep agent instructions short and procedural; do not copy the full product spec into them.
