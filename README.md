# Journal transcription manager

A local-first app for organizing voice journal recordings, reviewing transcripts against audio, and running saved text-processing pipelines.

MVP1 is implemented as a local React/TypeScript interface backed by a Python FastAPI service and SQLite catalog. Development is divided into reviewed milestones so the interface and workflows can be adjusted before the next feature is started.

## Roadmap

1. MVP1 — Audio library: import, organize into groups, filter/sort, inspect metadata, and move recordings to the Recycle Bin.
2. MVP2 — Transcript workflows: configure and run reusable text-processing pipelines on existing or fixture transcripts.
3. MVP3 — Transcription and review: connect an ASR provider, show timed transcripts, play and seek audio, edit text, and preserve raw history.

See [MVP_PLAN.md](MVP_PLAN.md) for the sequence and [docs/mvp/](docs/mvp/) for detailed scope and verification checklists.

## Run locally on Windows

1. Install backend packages from the project root with `py -m pip install -r backend/requirements.txt`.
2. In a terminal, start the API with `py -m uvicorn app.main:app --app-dir backend --reload`.
3. In another terminal, run `cd frontend`, `npm install`, and `npm run dev`.
4. Open the local URL printed by Vite (normally `http://localhost:5173`).

For MVP2 OpenRouter runs, set `OPENROUTER_API_KEY` in the same terminal environment before starting the API. The key is read by the backend and is not saved in the project or SQLite. You can create or edit pipelines without a key; a key is required to execute a provider call. Enter OpenRouter model IDs in each stage's model field.

Run backend checks from the `backend` folder with `py -m pytest --basetemp=backend-test-tmp`. Run frontend checks from the project root with `npm --prefix frontend test` and `npm --prefix frontend run build`.

The catalog and audio files are stored under `%LOCALAPPDATA%\JournalTranscriber\Library` by default. Set `JOURNAL_LIBRARY_DIR` before starting the API to choose another folder.

## Privacy

The application is intended to keep the audio library and transcript data on the user's computer. Selected transcription or language-model providers will receive the data required for the operation. Do not commit personal recordings, transcripts, database files, or API keys to this repository.

## Development status

The implementation stack and data flow are documented in [ARCHITECTURE.md](ARCHITECTURE.md).
