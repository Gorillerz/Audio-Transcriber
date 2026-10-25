# Journal transcription manager

A local-first app for organizing voice journal recordings, reviewing transcripts against audio, and running saved text-processing pipelines.

MVP1 (Audio Library) and MVP2 (Transcript Workflows) are implemented as a local React/TypeScript interface backed by a Python FastAPI service and SQLite. MVP3 is in progress; local Whisper transcription is available through the configured WSL GPU setup, including as the first stage of a pipeline.

## Roadmap

1. MVP1 — Audio library: import, organize into groups, filter/sort, inspect metadata, and move recordings to the Recycle Bin.
2. MVP2 — Transcript workflows: configure and run reusable text-processing pipelines on existing or fixture transcripts.
3. MVP3 — Transcription and review: run local Whisper, use it as an optional first pipeline stage, then add timed transcript review, synchronized audio, and editing.

See [MVP_PLAN.md](MVP_PLAN.md) for the sequence and [docs/mvp/](docs/mvp/) for detailed scope and verification checklists.

## Run locally on Windows

1. Install backend packages from the project root with `py -m pip install -r backend/requirements.txt`.
2. In a terminal at the project root, start the API with `py -m uvicorn app.main:app --app-dir backend --reload`.
3. In another PowerShell terminal, run `cd frontend`, then `npm.cmd install` and `npm.cmd run dev`. Use `npm.cmd` if PowerShell blocks the `npm.ps1` script under its execution policy.
4. Open the local URL printed by Vite (normally `http://localhost:5173`).

For real MVP2 runs, open **Library settings** and enter your OpenRouter API key. It is stored in Windows Credential Manager, not in the project or SQLite. **Test Connection** checks the key with OpenRouter. `OPENROUTER_API_KEY` is supported as a development fallback. The model picker searches the current OpenRouter catalog, ordered newest first, and still accepts a manually entered model ID. A key is required only to make real provider calls. **Simulate** runs a local preview with labeled placeholder outputs and does not call OpenRouter; simulated runs exist only in the current browser session.

Pipeline runs can start from a selected official output such as Transcription or Cleanup, or begin with one local Transcription stage. Text-only pipelines require an official transcription to be available for every selected recording. A first Transcription stage uses audio, publishes its text as the official output, and can feed later OpenRouter stages. Local transcription requires the configured WSL Whisper GPU environment. OpenRouter stages require the key described above. Each run stage saves its input and output, and real run results persist in SQLite. The Pipeline tab estimates selected-recording tokens and OpenRouter costs; transcription itself runs locally. The Run tab shows queue progress and expandable stage input/output. The details panel shows one official output per stage name; reruns replace the official result and archive the old one under Previous Versions, where outputs can be inspected and restored.

Run backend checks from the `backend` folder with `py -m pytest --basetemp=backend-test-tmp`. Run frontend checks from the project root with `npm.cmd --prefix frontend test` and `npm.cmd --prefix frontend run build` in PowerShell (or use `npm` where its script is permitted).

This checkout uses the local, Git-ignored `.journal-library-root` file to pin its existing library folder across backend restarts. Its relative path is resolved from the project root. If this file is absent, the API uses `%LOCALAPPDATA%\JournalTranscriber\Library` by default; `JOURNAL_LIBRARY_DIR` can select a library when there is no project-local pin. If a pinned folder is missing, the API stops with an error instead of creating a new empty library. The pin file is ignored by Git and is not published with the project.

## Privacy

The application is intended to keep the audio library and transcript data on the user's computer. Selected transcription or language-model providers will receive the data required for the operation. Do not commit personal recordings, transcripts, database files, or API keys to this repository.

## Development status

The implementation stack and data flow are documented in [ARCHITECTURE.md](ARCHITECTURE.md).
