# MVP3 — Transcription and review

## Goal

Connect a real speech-to-text provider and make timed transcripts useful for listening, correction, and later processing.

## Included

- Provide a transcription model/provider selector with capability information such as language support and word/segment timing.
- Start transcription for one recording or a selected batch.
- Show queue state, elapsed time, progress when available, and per-recording errors/retries.
- Save the raw provider response and normalized transcript as immutable raw history.
- Display transcript in timestamped and plain-text views.
- Play audio in the recording panel.
- Clicking a word or segment seeks to its start time; playback highlights the current timed item where alignment permits.
- Edit transcript text and save an edited version while preserving raw text and original timings/history.
- Run MVP2 pipeline stages using the resulting raw transcript.

## Acceptance criteria

- Provider configuration accurately shows available timing granularity.
- Timer runs during processing and stops with the job; progress does not claim precision the provider cannot report.
- Timestamped and plain-text views show the same transcript content.
- Clicking a timed word seeks close to that word's start; segment-only providers seek to segment start.
- Playback updates the current transcript selection when timing data is available.
- Editing and saving leaves raw transcript history unchanged and preserves timestamps as provenance.
- Cancel, retry, and failed jobs have clear outcomes and do not create duplicate recording identities.
- Provider and model, configuration, elapsed time, and run status are recorded.

## Automated test checklist

- Test normalization of provider word-level and segment-level results.
- Test transcription job states, elapsed-time handling, retries, and errors.
- Test plain/timestamped view consistency and seek target calculation.
- Test edited versions preserve raw response and provenance.
- Test an unavailable-timing provider is represented accurately in the UI model.

## User-run checklist

- Transcribe a short English recording and a French or mixed-language recording.
- Transcribe one recording and a batch; inspect elapsed time and failures.
- Click words and segments at several points and confirm playback seeks correctly.
- Play audio and confirm the current timed transcript item follows playback.
- Compare timestamped and plain-text display.
- Correct a word, save, reopen the recording, and confirm the correction persists.
- Inspect history and confirm the original raw transcription remains available.
- Run the text pipeline on the raw transcript and inspect the outputs.
