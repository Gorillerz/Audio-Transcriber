# MVP2 — Transcript workflows

## Goal

Let the user define reusable processing pipelines, connect one step's output to another step's input, and run the pipeline on one or many recordings. Use existing or fixture raw transcripts while the real transcription provider is still being selected and integrated in MVP3.

## Included

- Define, name, edit, save, and duplicate pipeline configurations.
- Configure each step with a provider/model, prompt, input source, and expected output shape.
- Use one step's named output as the next step's input.
- Support stages such as raw transcript input, cleanup, cleanup verification, summary/topics, and title.
- Run a pipeline for one recording or a selected batch.
- Show queued/running/succeeded/failed status for each recording and stage, with retry for failures.
- Preserve each stage output with its input reference, provider/model, prompt version, and run metadata.
- Allow review of outputs and errors from the recording details panel.

## Deferred

- Real ASR provider execution; that lands in MVP3.
- Editing timestamped words and synchronized audio playback.
- User-authored executable code in pipeline steps.
- Parallel job execution until rate and resource limits are understood.

## Acceptance criteria

- A saved pipeline can be applied to a single recording and a selected batch.
- A downstream step receives the output selected in its configuration, not an implicit or stale version.
- Every run saves its output and enough provenance to reproduce the configuration.
- A failed stage can be retried without rerunning successful recordings or stages unnecessarily.
- Editing a pipeline does not rewrite outputs from previous runs.
- Fixture transcript input allows the pipeline UI and execution flow to be reviewed without an ASR provider.

## Automated test checklist

- Test pipeline save/load and step ordering.
- Test input/output binding between steps.
- Test validation for missing input, model, prompt, or output schema.
- Test batch job state, partial failure, retry, and output provenance.
- Test that changing a pipeline leaves prior run records intact.

## User-run checklist

- Create a pipeline with cleanup, verification, summary, and title stages.
- Change the input binding for one stage and confirm the result uses the selected prior output.
- Run against one fixture transcript and a batch of fixtures.
- Confirm progress and failures are visible per item and per stage.
- Retry one failed item and confirm successful outputs remain unchanged.
- Edit a pipeline and confirm earlier runs retain their original configuration and outputs.
