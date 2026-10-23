# MVP2 — Transcript workflows

## Goal

Create reusable text-processing pipelines that can be run against saved raw transcript text for one or many recordings. Real audio-to-text transcription remains in MVP3.

## Implemented

- Paste or edit plain-text raw transcripts from a recording details panel. Saving appends a version and preserves the earlier text.
- Create, edit, save, and duplicate named pipeline definitions.
- Add ordered stages and configure each stage with a type, OpenRouter model ID, prompt, input source, and text or JSON output format.
- Bind a stage to the raw transcript or an earlier stage's named output. Forward references are rejected.
- Run a pipeline on one recording or a batch selected from the audio library.
- Display queued, running, succeeded, and failed status for each stage and recording, with output and errors.
- Retry failed stages while retaining successful stage outputs.
- Store an immutable pipeline snapshot, frozen raw input version, stage input/output, model, prompt, prompt hash, and timestamps with each run.
- Process jobs one at a time on a background worker. Queued and interrupted runs are recovered when the local API starts.

## Setup and limits

- Set `OPENROUTER_API_KEY` in the environment used to start FastAPI before executing a provider call. The key is not stored in SQLite or source files.
- Enter an OpenRouter model ID in each stage. Model IDs are currently free-text fields; the app does not fetch a live model catalog.
- Stage prompts and text are sent to OpenRouter only when the user launches a pipeline. Audio is not sent to OpenRouter.
- JSON stages request JSON mode and fail visibly if the provider returns invalid JSON.
- MVP2 supports saved or fixture plain text. Real ASR, timestamped transcript editing, synchronized playback, and export files are deferred.

## Acceptance criteria

- A saved pipeline can be applied to a single recording or a selected batch with a saved raw transcript.
- Raw transcript saves append versions, and a run uses the raw version captured at queue time.
- A downstream stage receives exactly the raw or earlier-stage output selected in its configuration.
- Every run preserves the pipeline revision, provider/model, prompt/hash, input reference, stage input/output, and status.
- A failed stage can be retried without rerunning successful stages or overwriting their output.
- Editing or duplicating a pipeline does not rewrite prior run snapshots or outputs.
- A fixture transcript can exercise the whole workflow without an ASR provider.

## Automated checks

- Backend tests cover raw transcript versioning, pipeline validation and input binding, immutable run snapshots, and retry behavior that preserves successful outputs.
- Frontend build and existing catalog helper tests run with `npm --prefix frontend run build` and `npm --prefix frontend test`.
- Backend tests run with `py -m pytest --basetemp=backend-test-tmp` from `backend/`.

## User-run checklist

- Set an OpenRouter key in the API process environment, restart FastAPI, and confirm no key is displayed in the UI.
- Open a recording, paste a short fixture transcript, save it, change it, and save again; confirm earlier raw versions remain available.
- Create a pipeline with cleanup, verification, summary, and title stages. Enter a model ID and prompt for each stage.
- Bind a later stage to an earlier output; run once, change it to raw input, and compare the results.
- Select one recording and then multiple recordings and run the pipeline. Watch per-stage status and inspect outputs.
- Force a provider error (for example, an invalid model ID), fix the configuration or key, retry, and confirm completed stages retain their previous output.
- Edit or duplicate a pipeline after a run and confirm its earlier run keeps the old pipeline revision and prompt.
- Restart FastAPI while a run is queued or active and confirm its saved state resumes.
