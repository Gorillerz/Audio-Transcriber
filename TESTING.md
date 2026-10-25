# Testing and review

Each MVP brief defines acceptance criteria, automated coverage/checks, and a user-run checklist. Automated tests protect behavior that can be reproduced consistently. The user-run checklist covers media handling, UI interaction, and real-provider behavior that needs the user's machine or judgment.

For every MVP, the agent should:

- Add focused automated tests alongside the feature.
- Keep test fixtures synthetic or explicitly safe to publish; never use private journal audio or transcripts in the public repository.
- Run the relevant automated checks for each MVP and report what ran, including failures and environment limitations.
- Give the user the manual checklist in a concise format and capture any reported issues in the active MVP brief.
- Avoid claiming a behavior is verified when a test was written but not run.

## Current automated coverage

- Backend `pytest` tests cover catalog import and identity, metadata matching, manual status, recycle-bin behavior, raw transcript versioning and per-version provider/model provenance, legacy provenance recovery, OpenRouter key/model-catalog behavior, official output replacement/archive/restore/order/rename, per-recording output-name overrides, selected-source snapshots, transcription requirements, pipeline validation, and retry behavior.
- Catalog startup tests verify stale audio paths are repaired only when a file under the active recording folder has the catalog's exact content hash; audio bytes are never moved or rewritten by path repair.
- MVP3 backend tests cover the measured Whisper runtime estimate, live GPU-probe response shape, transcription result persistence, per-word probability normalization and exact transcript-version alignment, and interrupted-run recovery. Pipeline workflow tests also cover the unique first-position ASR stage, model allowlisting, audio-first run creation, raw transcript persistence, and handoff to a later text stage. They do not invoke WSL or process personal audio.
- Audio playback tests use synthetic WAV bytes and mocked FFmpeg processes. They verify normalized cached waveform peaks, one-time fallback MP3 generation, and that the original audio bytes remain unchanged. Frontend helper tests cover seek clamping and the supported playback-rate range.
- Library-path tests verify the project-local pin wins across shell environment changes and a missing pinned folder fails clearly instead of opening a blank catalog.
- Frontend `vitest` currently covers catalog date/duration, output word-count and confidence-color formatting, exact transcript/alignment matching, output collapse-state logic, combined status/duration filtering, sorting, audio seek clamping, and playback-rate bounds. The production build runs TypeScript checking before Vite bundling.
- Output management APIs are covered through WorkflowStore behavior tests. The details-panel ordering, restore-name prompt, and pipeline source selector still require the MVP2 user-run checklist because they do not yet have browser-component tests.

## Commands on Windows PowerShell

From the project root, run frontend checks with `npm.cmd --prefix frontend test` and `npm.cmd --prefix frontend run build`. Run backend tests from `backend/` with `py -m pytest --basetemp=backend-test-tmp`. `npm.cmd` invokes npm's command shim directly when PowerShell's execution policy blocks `npm.ps1`.

The active MVP brief is the source of its acceptance criteria and checklist. Update `PRODUCT_SPEC.md` for changed user behavior and `ARCHITECTURE.md` for changed technical decisions after each MVP review or major change.
