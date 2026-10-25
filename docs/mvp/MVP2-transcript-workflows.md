# MVP2 — Transcript workflows

## Status

Complete and reviewed. MVP2's original scope is text-only processing. MVP3 adds an optional local transcription stage that can start a pipeline from audio.

## Goal

Create reusable text-processing pipelines that run against an official output for one or many recordings. Local audio-to-text transcription is provided by MVP3; text stages still require an official transcription to be available.

## Implemented

- Preserve raw transcript text as append-only versions. Local transcription publishes its latest successful text as the official **Transcription** output.
- Create, edit, save, and duplicate named pipeline definitions.
- Add ordered stages and configure each stage with a type, OpenRouter model ID, prompt, and input source. Model responses are handled as text.
- Search the process-cached OpenRouter model catalog by name, publisher, or ID; suggestions show publisher and input/output USD cost per million tokens, with newest models first. Existing free-form model IDs remain editable.
- Choose the pipeline's starting official output (such as Transcription or Cleanup), then bind each stage to that input or an earlier stage's output. Forward references are rejected.
- Reserve the output name **Transcription** for local ASR; a text stage cannot replace the official transcript needed by later text-only runs.
- Define an ordered pipeline and review a visual stage flow, including the cleanup prompt, before running it.
- Estimate selected recordings, tokens, and stage input/output costs before execution. Estimates use about four characters per token, 90% of the raw transcript tokens for cleanup and verification output, 500 words for summaries, and 10 words for titles; actual usage varies by model tokenizer and response.
- Run a pipeline on one recording or a batch selected from the audio library.
- Display queued, running, succeeded, and failed status for each stage and recording, with output and errors.
- Use separate **Pipeline** and **Run** tabs with the saved-pipeline and recent-run sidebar visible on both. Pipeline contains the stage editor. Run shows the batch recording queue beside the vertical execution flow. Queue entries show ready, queued, processing, completed, or failed status; the current recording is animated and the panel reports its position and number remaining. Selecting another queue item changes the flow details without hiding which recording is processing.
- Show elapsed time for running or completed stages. Run flow blocks show API input and output, initially abbreviated to 20 words with an expand control for the full text.
- Simulate the first selected recording's pipeline locally without calling OpenRouter. Simulations use the chosen official output and stay in Recent Runs only for the current browser session; they are not persisted.
- Retry failed stages while retaining successful stage outputs.
- Store an immutable pipeline snapshot, exact selected official input name/content, stage input/output, model, prompt, prompt hash, and timestamps with each run.
- Publish each successful stage as the current official output named after the stage. Rerunning a stage with the same name replaces its official output and moves the old content to Previous Versions. Failed stages do not replace official output.
- Show unnumbered official outputs in the recording details panel. Pin Transcription first, allow other outputs to be reordered, and move removed outputs to Previous Versions.
- Rename a non-transcription official output by double-clicking its name in Recording Details. Enter or blur saves; names are unique per recording, duplicate names show a red inline warning, and Transcription stays fixed. A chosen name remains in effect for later runs of the same pipeline step on that recording.
- Show each official output's word count beside its creation time and provider/model; show the same count in Previous Versions metadata.
- Keep Previous Versions collapsed by default. Each entry shows stage name/type, execution and archive times, archive reason, provider/model, exact output, and a Restore action. If its name is already occupied, require a new name; restoring keeps the history entry intact.
- Process jobs one at a time on a background worker. Queued and interrupted runs are recovered when the local API starts.

## Setup and limits

- Enter an OpenRouter key in **Library settings** before executing a provider call. The key is stored in Windows Credential Manager and is not stored in SQLite or source files. `OPENROUTER_API_KEY` remains available as a fallback when no saved key exists.
- Use **Test connection** to validate a typed key before saving or check the currently active key. The app calls OpenRouter's current-key endpoint and does not retain or display the key during the check.
- The app requests OpenRouter's model catalog once when the browser app loads. The backend caches the upstream response for its process lifetime; reopening the workflow editor does not fetch it again. A selected list entry stores its exact model ID in the pipeline.
- Stage prompts and text are sent to OpenRouter only when the user launches a pipeline. Audio is not sent to OpenRouter.
- The pipeline output format is always text. The interface has no output-format selector; legacy JSON settings are normalized to text.
- MVP2's original workflow supports saved or fixture plain text. The MVP3 extension can now place one local ASR stage at the start of a pipeline; timestamped transcript editing, synchronized playback, and export files remain future work.
- The recording details panel is focused on file information and saved pipeline outputs; its former raw transcript input editor has been removed. Existing raw transcript versions remain in storage.

## Acceptance criteria

- A text-only pipeline can run only when every recording has an official transcription and the configured starting official output.
- A run uses the exact selected official output text frozen at queue time, even if the output is later replaced or archived.
- A downstream stage receives exactly the selected starting official output or earlier-stage output configured for it.
- Rerunning a stage name replaces its one official value and preserves its predecessor in the archive.
- Removing an official output archives it; restoring an archived value keeps its history record and refuses name collisions until a different name is supplied.
- Transcription is pinned at the top of the details panel. Reordering other outputs persists across reloads.
- Double-clicking a non-transcription output title opens its inline editor. Enter and blur save the name; Escape cancels. Duplicate names produce the exact message “This stage name is already used for this recording” and a red input glow, and the API rejects the same conflict. Transcription cannot be renamed.
- A renamed output keeps its custom name when the same pipeline step runs again; the previous official text is still retained in Previous Versions.
- Every run preserves the pipeline revision, provider/model, prompt/hash, input reference, stage input/output, and status.
- A failed stage can be retried without rerunning successful stages; a failed attempt leaves its previous official output untouched.
- Editing or duplicating a pipeline does not rewrite prior run snapshots or outputs.
- A fixture transcript can exercise the whole workflow without an ASR provider.
- When an MVP3 local transcription stage is used, it appears at most once and first; its saved raw text can feed a later pipeline stage.
- The recording details panel shows named current outputs without run numbers or a run selector. The Run page remains the place to inspect execution status and full run history.
- Current outputs and Previous Versions display a whitespace-based word count beside their other metadata.

## Automated checks

- Backend tests cover raw transcript versioning, OpenRouter credentials/model catalog, output replacement/archive/restore, output order, selected-source snapshots, transcription requirements, pipeline validation, and retry behavior. Run with `py -m pytest --basetemp=backend-test-tmp` from `backend/`.
- The frontend build and existing catalog helper tests run with `npm.cmd --prefix frontend run build` and `npm.cmd --prefix frontend test` from Windows PowerShell at the project root (`npm` works where its script is permitted). Output-management interactions currently use the user-run checks below.

## User-run checklist

- Enter an OpenRouter key in Library settings, save it, close and reopen settings, and confirm the app reports that a key is available without displaying its value.
- Test a valid key and an invalid key; confirm each result is reported clearly and an unsaved key is not saved by testing it.
- Search for a model by name, publisher, and ID; confirm each result shows publisher and input/output price, selecting it fills the model ID, and a custom model ID can still be typed.
- Remove the saved key and confirm the status updates. If `OPENROUTER_API_KEY` is configured, confirm the environment fallback remains active.
- Open a recording with existing raw transcripts and pipeline runs. Confirm the latest transcript and successful named stages appear as official outputs and older same-name values appear under Previous Versions.
- Create a pipeline with cleanup, verification, summary, and title stages. Enter a model ID and prompt for each stage.
- Bind a later stage to an earlier output; run once, change the pipeline's starting official output, and compare the results.
- Select one recording and then multiple recordings. Configure or select a saved pipeline on the Pipeline tab, then start the run. Confirm the app opens the Run tab, shows the queue and current position, animates the active recording and stage, and updates the flow as the batch advances.
- While a batch is running, select a different queue item and inspect its flow. Confirm the queue still marks the actual processing recording and the run progress remains accurate. Open a recent run and confirm its recording queue and saved outputs appear on the Run tab.
- Run the same stage twice with the same name. Confirm its newest output becomes official and its predecessor appears under Previous Versions with type, timestamps, and provider/model.
- Remove an official output and confirm it moves into Previous Versions. Restore one with a free name, then restore an older same-name item and supply a different name when prompted.
- Reorder two non-transcription outputs, close and reopen the recording, and confirm the order persisted while Transcription stays first.
- Double-click a non-transcription output name and rename it with Enter, then rename another with blur. Confirm the name persists after reload and after rerunning that pipeline stage. Try a duplicate name and Transcription; confirm both are rejected and the duplicate warning has a red glow.
- Open a recording with current outputs and Previous Versions. Confirm each count matches the visible text, including a short or empty output if present.
- Run a text pipeline first from Transcription and then from a Cleanup output. Confirm the Run flow displays the selected input and each stage receives its exact frozen text.
- Archive the only official transcription and confirm text-only pipelines cannot start until a transcription is restored or recreated.
- Use the Run page to inspect an earlier execution's stage input/output and status; the details panel now shows current outputs rather than run selection.
- Expand the recording and cost breakdown boxes. Confirm the selected recordings, token estimates, and per-stage input/output estimates update as the pipeline, model, or selected recordings change; treat costs as estimates, not a quote.
- Use **Simulate** with an official starting output. Confirm it exercises the flow and shows labeled simulated outputs without making an OpenRouter request. Confirm the simulation is gone after refreshing the browser.
- In the Run tab, expand API input and output blocks and confirm the full text can be inspected; verify stage elapsed time updates while a real stage is running.
- Force a provider error (for example, an invalid model ID), fix the configuration or key, retry, and confirm completed stages retain their previous output.
- Edit or duplicate a pipeline after a run and confirm its earlier run keeps the old pipeline revision and prompt.
- Restart FastAPI while a run is queued or active and confirm its saved state resumes.
