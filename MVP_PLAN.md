# MVP plan

Work through one milestone at a time. MVP1 and MVP2 are implemented and reviewed. MVP3 is in progress one small slice at a time. Update the active brief as features and decisions change.

## Sequence

| Milestone | Goal | Status | Brief |
|---|---|---|---|
| MVP1 — Audio library | Build the recording catalog with import, filters, sorting, persistent groups, safe deletion, and a metadata side panel. | Complete | [docs/mvp/MVP1-audio-library.md](docs/mvp/MVP1-audio-library.md) |
| MVP2 — Transcript workflows | Save versioned raw text, configure reusable OpenRouter stages, and run/review them on one or many recordings. | Complete | [docs/mvp/MVP2-transcript-workflows.md](docs/mvp/MVP2-transcript-workflows.md) |
| MVP3 — Transcription and review | Run local ASR directly or as the unique first pipeline stage; show progress, timed and plain transcripts, audio seeking, editing, and raw history. | In progress — local ASR and audio player implemented | [docs/mvp/MVP3-transcription-review.md](docs/mvp/MVP3-transcription-review.md) |

## Review loop

For each active MVP:

1. Read the brief and identify the smallest useful vertical slice.
2. Implement only that MVP's scope and document the code using `AGENTS.md` guidance.
3. Add automated tests for behavior that can be checked reliably in code.
4. Run the automated checks as part of the MVP and report their results.
5. Give the user the manual checklist from the brief and collect their observations.
6. Update the brief, product spec, and architecture when the review changes requirements or decisions.
7. Start the next MVP only after the current result is reviewed and its status is updated above.

## Shared testing expectations

See [TESTING.md](TESTING.md). Every MVP brief contains its own acceptance criteria and user-run checklist.
