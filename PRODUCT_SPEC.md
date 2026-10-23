# Journal transcription manager

## Purpose

A private, local-first app for importing voice journal recordings, tracking transcription work, reviewing timed transcripts against audio, and keeping edited and processed outputs organized.

## Primary user

One person managing personal recordings, mostly English with some French and occasional language switching.

## MVP sequence

Implement and review one MVP at a time. Each MVP has its own brief in `docs/mvp/` with scope, acceptance criteria, automated checks, and a user-run checklist. Update these documents after each review before starting the next MVP.

1. **MVP1 — Audio library:** import and catalog recordings; search/filter/sort; inspect metadata in a side panel; establish the basic visual layout. Audio playback is a stretch item for this MVP and can be promoted into scope after the layout is reviewed.
2. **MVP2 — Transcript workflows:** configure and run saved processing pipelines on existing or imported raw transcripts, individually or in batches; inspect stage outputs and failures. Use fixture transcripts for pipeline development where real ASR is not yet available.
3. **MVP3 — Transcription and review:** connect a real transcription provider, show run timing and progress, display plain and timestamped output, seek audio from transcript words, edit aligned text, and preserve raw history.

## V1 user outcomes

- Import audio by dropping files into the app or into a configured inbox folder.
- See every known recording, its transcription status, and its group/type.
- Identify renamed files by content hash where possible; show likely metadata matches for confirmation when bytes differ.
- Select multiple recordings and run transcription as a batch with visible progress, retry, and error details.
- Keep the original audio and raw transcript intact.
- Review a transcript beside an audio player. Selecting a timed word or segment seeks to that point and plays the recording.
- Edit transcript text and retain the original model output and edit history.
- Run configurable cleanup, title, summary, and other text-model stages through OpenRouter.
- Export readable text and structured JSON for each recording.

## V1 scope

- Single-user app running on the user's computer.
- Local audio and transcript storage with a local database for the catalog and job state.
- English/French transcription and word-level timing, selected per provider capability.
- User-configured processing stages with an explicit model, prompt, and output format for each stage.
- Basic groups such as journal, meeting, idea, or custom labels.

## Not in V1

- Multi-user accounts, cloud synchronization, or a hosted public service.
- Mobile recording or live transcription.
- Arbitrary user-written Python/JavaScript pipeline code.
- Automatic destructive edits to source recordings or raw transcripts.

## Acceptance checks

- Importing the same file twice does not create two recordings.
- Renaming a byte-identical recording still links it to its existing catalog entry.
- A metadata-only possible match is not silently treated as the same recording.
- A failed batch item can be retried without rerunning successful items.
- Clicking a timed transcript item seeks the player to its start time.
- Editing or cleaning a transcript never replaces the preserved raw transcription.
- Each generated result records the provider/model and prompt or stage version that produced it.

## Open decisions for implementation

- Which transcription provider wins on representative English/French recordings after a small accuracy, timestamp, cost, and privacy comparison.
- Whether the initial local transcription runner uses a hosted GPU or a supported local path.
- Whether the inbox is watched continuously or scanned when the app opens.
- Whether audio playback is included in MVP1 or moved to MVP3 with timed transcript review.
