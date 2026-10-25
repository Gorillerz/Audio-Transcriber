# Journal transcription manager

## Purpose

A private, local-first app for importing voice journal recordings, tracking transcription work, reviewing timed transcripts against audio, and keeping edited and processed outputs organized.

## Primary user

One person managing personal recordings, mostly English with some French and occasional language switching.

## MVP sequence

MVP1 and MVP2 are implemented and reviewed. MVP3 is in progress, adding local Whisper selection and run progress, including an optional audio-to-transcript first stage in saved pipelines. Each MVP has a brief in `docs/mvp/` with scope, acceptance criteria, automated checks, and a user-run checklist.

1. **MVP1 — Audio library:** import and catalog recordings; search/filter/sort; organize recordings into named groups; inspect metadata in a side panel; move unwanted audio to the operating system trash after confirmation.
2. **MVP2 — Transcript workflows:** save versioned raw transcript text; configure and run OpenRouter text pipelines on existing or fixture transcripts, individually or in batches; inspect stage outputs, provenance, and failures. MVP3 adds an optional local transcription stage at the start of a pipeline.
3. **MVP3 — Transcription and review:** launch local word-timed Whisper transcription, show run timing and progress, display plain and timestamped output, seek audio from transcript words, edit aligned text, and preserve raw history.

The first MVP3 audio-playback slice is implemented: the Recording Details panel has a waveform player with play/pause, five-second skip controls, and speeds through 2×. Timed transcript words seek and play their audio position. Browser-incompatible source formats use an FFmpeg-generated cached MP3 rendition; the original recording remains unchanged.

## V1 user outcomes

- Import audio by dropping files into the app or into a configured inbox folder.
- See every known recording, its transcription status, and its group/type.
- Identify renamed files by content hash where possible; show likely metadata matches for confirmation when bytes differ.
- Allow a user to record the known status of pre-existing transcripts while leaving the raw transcript import for a later milestone.
- Select multiple recordings and run transcription as a batch with visible progress, retry, and error details.
- Keep the original audio and raw transcript intact.
- Review a transcript beside an audio player. Selecting a timed word or segment seeks to that point and plays the recording.
- Edit transcript text and retain the original model output and edit history.
- Run configurable cleanup, title, summary, and other text-model stages through OpenRouter.
- Configure saved pipelines and ordered stages on a dedicated Pipeline tab. Monitor batch runs on a Run tab with a vertical recording queue beside the execution flow; animate the active recording and stage and show outputs as they complete.
- Optionally begin a pipeline with one local audio transcription stage, select its supported model, then pass the generated raw transcript into later text stages. The transcription stage is unique and stays first; later stages continue to use OpenRouter.
- Select local transcription providers per recording, see the detected compute device and an approximate benchmark-based runtime, then launch and monitor the transcription.
- View one official output per output name in each recording's details panel. A successful stage replaces the official output with the same name and moves the replaced content into **Previous Versions**.
- Keep the Transcription output pinned first; let users reorder other official outputs and move any output into Previous Versions.
- Let users double-click a non-transcription output name in Recording Details to rename it. Names must be unique within that recording; a duplicate shows an inline red warning, and Enter or leaving the field saves a valid name. Transcription cannot be renamed.
- Show a word count beside the date and provider/model metadata for each current output and previous version in Recording Details.
- For Whisper transcriptions, color each aligned word by its saved probability, show the percentage on hover, and provide a control at the top-right of the transcript to hide or show colors. Leave unscored or misaligned transcripts plain.
- Give Recording Details text containers up to twice their previous height (520px, with scrolling for longer text) without enlarging the text. Keep per-block collapse/expand controls and a **Collapse All / Expand All** control beside output refresh.
- Inspect each previous version's stage name/type, execution and archive time, provider/model, and exact output text. Restore an archived item; when its name is already in use, ask the user for a new name.
- Select an official output such as Transcription or Cleanup as the starting text for a pipeline. Any pipeline with a non-ASR stage requires an official transcription to remain available; a first-stage ASR run creates one.
- Keep the recording details panel focused on file information and saved pipeline outputs: show the filename within File Information, and omit the separate file icon/status header, Processing section, and raw transcript input editor.
- Preview stages and approximate token/cost estimates before starting a pipeline. A local simulation shows the run flow without contacting OpenRouter; simulations are temporary and are not saved as real runs.
- Export readable text and structured JSON for each recording.

## V1 scope

- Single-user app running on the user's computer.
- Local audio and transcript storage with a local database for the catalog and job state.
- English/French transcription and word-level timing, selected per provider capability. The first real integration is Whisper medium in the user's configured WSL GPU environment; the option identifies the GPU at runtime and reports the benchmark estimate as approximate.
- User-configured processing stages with an explicit OpenRouter model and prompt. Pipeline responses are text-only.
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
- Selected recordings can be added to a new or existing group; selecting a group in the sidebar filters the catalog to its members.
- Recordings with no group display an empty marker in the table; recordings in multiple groups show each group name.
- A single recording or a selected batch can be moved to the operating system's Recycle Bin after a confirmation warning.
- Pipeline runs freeze the selected official output text and pipeline configuration; text-only runs require an official transcription to be available.
- Pipeline stages can take the selected initial official output or an earlier stage output, and each stage records its model, prompt hash, input, output, and status.
- A pipeline may contain at most one local transcription stage, and it must be first. When present, audio is transcribed locally and the generated raw transcript is saved as a new raw version before text stages run.
- The output name **Transcription** is reserved for ASR so a text stage cannot replace the required official transcript.
- A successful stage becomes the current official output under its stage name. A same-name rerun archives the previous value before replacing it; failures leave the current official value alone.
- Removing an official output moves it into Previous Versions. Restoring keeps the archived entry and asks for a new output name when the old name is occupied.
- The details panel displays unnumbered official outputs with Transcription pinned first and other outputs reorderable. Previous Versions is collapsed by default; the Run page shows execution records and run-specific outputs.
- Failed pipeline stages can be retried without replacing outputs from successful stages.
- A failed batch item can be retried without rerunning successful items.
- Pipeline editing and run monitoring are separate tabs. The Run tab shows each batch recording's status, highlights the current recording, reports its position and remaining count, and updates the execution flow when a queue item is selected.
- Each run stage saves its input/output, status, model, prompt provenance, and timing; the run flow shows the first 20 words of input/output with an option to expand.
- The recording details panel starts with File Information including the filename, then shows saved Pipeline Outputs without a separate Processing section or raw transcript input editor.
- Simulation runs are clearly labeled, make no provider calls, and are not persisted beyond the current browser session.
- Clicking a timed transcript item seeks the player to its start time.
- Editing or cleaning a transcript never replaces the preserved raw transcription.
- Each generated result records the provider/model and prompt or stage version that produced it.

## Open decisions for implementation

- Whether Whisper medium remains the best provider after representative English/French recordings are manually checked for accuracy and speed. Current RX 9060 XT GPU timing is based on one 60-second excerpt.
- Whether the inbox is watched continuously or scanned when the app opens.
