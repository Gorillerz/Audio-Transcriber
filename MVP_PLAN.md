# MVP plan

Work through one milestone at a time. After each milestone, review the result, complete its verification checklist, and revise the brief based on feedback before moving forward.

## Sequence

| Milestone | Goal | Brief |
|---|---|---|
| MVP1 — Audio library | Build the recording catalog and visual layout, with import, filters, sorting, and a metadata side panel. | [docs/mvp/MVP1-audio-library.md](docs/mvp/MVP1-audio-library.md) |
| MVP2 — Transcript workflows | Configure reusable processing stages and run them on one or many existing/fixture transcripts. | [docs/mvp/MVP2-transcript-workflows.md](docs/mvp/MVP2-transcript-workflows.md) |
| MVP3 — Transcription and review | Connect real ASR; show progress, timed and plain transcripts, audio seeking, editing, and raw history. | [docs/mvp/MVP3-transcription-review.md](docs/mvp/MVP3-transcription-review.md) |

## Review loop

For each MVP:

1. Read the brief and identify the smallest useful vertical slice.
2. Implement only that MVP's scope and document the code using `AGENTS.md` guidance.
3. Add automated tests for behavior that can be checked reliably in code.
4. Run the automated checks as part of the MVP and report their results.
5. Give the user the manual checklist from the brief and collect their observations.
6. Update the brief, product spec, and architecture when the review changes requirements or decisions.
7. Start the next MVP only after the current result is reviewed.

## Shared testing expectations

See [TESTING.md](TESTING.md). Every MVP brief contains its own acceptance criteria and user-run checklist.
