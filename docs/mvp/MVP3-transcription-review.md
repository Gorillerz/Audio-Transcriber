# MVP3 — Transcription and review

## Status

In progress. The initial vertical slice adds a provider picker and launches local Whisper medium in the configured WSL GPU environment. Pipelines can start with one local transcription stage and continue with OpenRouter text stages. The audio player and waveform slice is now implemented. Editing, a standalone transcription batch queue, and richer timestamp review remain future MVP3 slices.

## Goal

Connect a real speech-to-text provider and make timed transcripts useful for listening, correction, and later processing.

## Current slice

- The recording details panel opens a transcription dialog with available provider information.
- The local Whisper option reports live WSL/PyTorch GPU readiness, GPU name, language support, and word-level timestamp capability.
- The warm runtime estimate is based on the RX 9060 XT 60-second Whisper medium benchmark (19.45 seconds inference per 60 seconds of audio plus 12.1 seconds startup). It is approximate and excludes a first model download.
- Launching runs Whisper medium in WSL, shows an animated indeterminate progress bar, elapsed time, and estimated remaining time, and saves the provider result, model/device provenance, word timings, and per-word probabilities in SQLite. Each raw transcript version stores its provider/model, and extracted text is published as the current official **Transcription** output; any replaced official transcript moves into Previous Versions.
- The Recording Details panel colors aligned Whisper words from red through orange and yellow-green to green at the 25%, 50%, 75%, and 100% anchors. Hovering a scored word shows its probability; a control at the transcript's top-right toggles colors without hiding the score tooltip.
- Recording Details shows a waveform player above Pipeline Outputs with play/pause, five-second backward/forward controls, a seekable waveform, elapsed/total time, and playback rates through 2×. Timed transcript words seek to their exact start and start playback; the currently playing timed word is highlighted.
- Waveform peaks are generated with FFmpeg and cached in the library using the audio content hash. Original audio is served directly when the browser supports its format; otherwise the app generates and caches an MP3 fallback. Neither derivative changes the source audio. The waveform represents audio level and pauses, not speech detection.
- Recording Details text containers can grow to 520px (twice the previous 260px limit), with scrolling for longer text and the original text size preserved. Each output and previous version can collapse its text while keeping its title and metadata visible; **Collapse All / Expand All** controls every output block beside refresh.
- The Pipeline editor offers a **Transcription** stage with a local model selector. Selecting it moves that stage to the beginning; a pipeline can contain only one. Running it on a batch transcribes each recording in order, preserves the provider result and word timings through the existing transcription history, appends raw text, publishes the official Transcription output, and feeds that text into later pipeline stages.
- Pipelines starting with transcription do not require an existing raw transcript. A transcription stage is local ASR and has no OpenRouter prompt or model; later text stages keep their OpenRouter model and prompt settings.
- Run status and outputs persist. If the local API restarts during transcription, the run becomes failed with a retry message rather than staying in a running state.
- Only one local transcription can run at once. Pipeline batch runs process selected recordings serially; a standalone transcription batch queue and cancellation are later slices.

## Included

- Provide a transcription model/provider selector with capability information such as language support and word/segment timing.
- Start transcription for one recording or a selected batch.
- Show queue state, elapsed time, progress when available, and per-recording errors/retries.
- Save the raw provider response and normalized transcript as immutable raw history.
- Show Whisper word probabilities on hover and allow transcript confidence colors to be hidden or shown.
- Display transcript in timestamped and plain-text views.
- Play audio in the recording panel.
- Draw and seek a waveform while playing audio; keep playback available when waveform generation fails.
- Use browser-native formats directly and use an FFmpeg-generated cached MP3 for formats the browser cannot play.
- Clicking a word or segment seeks to its start time; playback highlights the current timed item where alignment permits.
- Edit transcript text and save an edited version while preserving raw text and original timings/history.
- Run MVP2 pipeline stages using the resulting raw transcript.
- Start an MVP2 pipeline directly from audio with one first-position local transcription stage, then continue through one or more OpenRouter text stages.

## Acceptance criteria

- Provider configuration accurately shows available timing granularity.
- Pipeline validation accepts a single supported transcription model only in the first position; selecting the stage in the editor moves it to the start and refuses a duplicate.
- A pipeline beginning with transcription can run on a recording with no saved raw transcript. ASR output is appended as a new raw version, becomes the official Transcription output, and is passed to later text stages configured to use the starting input.
- Timer runs during processing and stops with the job; progress does not claim precision the provider cannot report.
- Timestamped and plain-text views show the same transcript content.
- Whisper confidence colors use red/orange/yellow-green/green at 25%/50%/75%/100%; hovering shows the saved probability and the button toggles color fills while retaining hover scores.
- Alignment is attached to the exact raw transcript version, and colors are shown only when its timed word text reconstructs that output. Manual or unscored legacy transcripts remain plain.
- Output text retains its original type size in a container up to 520px tall. Individual block controls collapse/expand text without hiding titles or metadata, and the header control collapses or expands all current and previous-version blocks together.
- Clicking a timed word seeks close to that word's start; segment-only providers seek to segment start.
- Playback updates the current transcript selection when timing data is available.
- The player provides play/pause, five-second skips, seekable waveform, elapsed and total time, and rate choices no faster than 2×. It does not modify the original audio.
- Waveform data is cached by audio content hash and its failure does not disable native audio playback. Unsupported browser formats use a cached MP3 rendition generated by FFmpeg.
- Editing and saving leaves raw transcript history unchanged and preserves timestamps as provenance.
- Cancel, retry, and failed jobs have clear outcomes and do not create duplicate recording identities.
- Provider and model, configuration, elapsed time, and run status are recorded.

## Automated test checklist

- Test the Whisper runtime estimate, provider capability response, persisted job result, and interrupted-run recovery.
- Test normalization of provider word-level and segment-level results.
- Test transcription job states, elapsed-time handling, retries, and errors.
- Test plain/timestamped view consistency and seek target calculation.
- Test waveform normalization/cache reuse, MP3 fallback/cache reuse, and source-audio immutability using synthetic files and mocked FFmpeg. Test player seek clamping and playback-rate limits.
- Test edited versions preserve raw response and provenance.
- Test an unavailable-timing provider is represented accurately in the UI model.
- Test transcription-stage uniqueness, first-position validation, model allowlisting, audio-first run creation, raw transcript persistence, and handoff to a later OpenRouter stage without invoking WSL.

## User-run checklist

- Open a recording's details and select **Start transcription**. Confirm the dialog identifies Whisper medium, the detected GPU (AMD Radeon RX 9060 XT), and an approximate runtime based on recording length.
- Launch a short English recording. Confirm the animation appears, elapsed time advances, the remaining-time estimate is shown, and the run completes with transcript text and timed-word count.
- Close and reopen the recording's transcription dialog while the run is active; confirm it restores the active run. After completion, confirm the recording is marked transcribed, the official Transcription appears in the details panel, and it is available as a pipeline input.
- Use **Retry transcription** after a failure and confirm a useful error appears when WSL/GPU/model setup is unavailable.
- Transcribe a short English recording and a French or mixed-language recording.
- Transcribe one recording and a batch; inspect elapsed time and failures.
- Click words and segments at several points and confirm playback seeks correctly.
- Play audio and confirm the current timed transcript item follows playback.
- Confirm the player appears above Pipeline Outputs; test play/pause, five-second rewind/forward, speed choices up to 2×, waveform seeking, and elapsed/total time.
- Click an aligned transcript word and confirm playback seeks to that word and highlights the word currently being played. Try a short WAV/MP3 and a format that requires browser fallback.
- Compare timestamped and plain-text display.
- In Recording Details, hover low-, medium-, and high-probability Whisper words and confirm their probability percentages appear. Use the top-right control to hide colors, confirm the scores still appear on hover, then show colors again. Confirm a manual transcript or one without saved probabilities stays uncolored.
- Confirm the output text is larger, collapse and reopen an individual output, then use the header control to collapse all and expand all. Check blocks under Previous Versions too.
- Correct a word, save, reopen the recording, and confirm the correction persists.
- Inspect history and confirm the original raw transcription remains available.
- Run a text pipeline from the official Transcription output and inspect the outputs.
- In Pipeline Workflows, add a Transcription stage after a text stage and confirm it moves to the start. Add another and confirm the duplicate is refused. Select the available local model, save, and confirm the model is retained after reloading.
- Run the pipeline on a short recording that has no saved raw transcript. Confirm the Run view shows a local transcription stage, followed by its transcript output and the configured text stages. Confirm the transcript appears in raw history and the later API stage receives that text.
