# Journal transcription manager

A local-first app for organizing voice journal recordings, reviewing transcripts against audio, and running saved text-processing pipelines.

This repository is at the planning stage. Development is divided into reviewed milestones so the interface and workflows can be adjusted before the next feature is started.

## Roadmap

1. MVP1 — Audio library: import and catalog recordings, filter/sort them, and inspect metadata.
2. MVP2 — Transcript workflows: configure and run reusable text-processing pipelines on existing or fixture transcripts.
3. MVP3 — Transcription and review: connect an ASR provider, show timed transcripts, play and seek audio, edit text, and preserve raw history.

See [MVP_PLAN.md](MVP_PLAN.md) for the sequence and [docs/mvp/](docs/mvp/) for detailed scope and verification checklists.

## Privacy

The application is intended to keep the audio library and transcript data on the user's computer. Selected transcription or language-model providers will receive the data required for the operation. Do not commit personal recordings, transcripts, database files, or API keys to this repository.

## Development status

The implementation stack and first library workflow are documented in [ARCHITECTURE.md](ARCHITECTURE.md). Setup instructions will be added with MVP1 once the runnable application exists.
