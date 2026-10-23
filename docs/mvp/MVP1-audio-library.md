# MVP1 — Audio library

## Goal

Create the first useful screen: a catalog of audio recordings with a clear selection and metadata view. Keep the layout easy to adjust before adding transcription workflows.

## Included

- Import one or more local audio files through a button and drag-and-drop.
- Assign each imported recording a stable ID and content hash so repeated imports and filename changes can be recognized. If the hash differs, show metadata-based matches as candidates for confirmation.
- Show recordings in a table with name, duration in minutes, date, and transcription status.
- Derive the status from transcript data associated with the catalog entry. If no known transcript is linked, show untranscribed; metadata-only matches remain candidates until confirmed.
- Give untranscribed recordings a subtle background hue and a text/icon status so color is not the only signal.
- Filter by transcription status and duration ranges, including under 10 minutes and over 40 minutes.
- Sort by each visible column.
- Select a row and show a right-side details panel with available file metadata and processing status/history.
- Show a useful empty state and import errors.
- Keep audio and generated library data outside the source repository by default.

## Deferred

- Transcription and text-model calls.
- Word-level transcript editing.
- Continuous folder watching.
- The audio player can be added after the initial layout review or in MVP3 with transcript synchronization.

## Acceptance criteria

- Importing multiple supported files adds one catalog row per distinct recording.
- Importing the same bytes again, including under a changed filename, does not create a duplicate catalog entry.
- A metadata-only match is shown for confirmation and is never silently labeled as the same recording.
- Unsupported or unreadable files produce a clear error and do not break the rest of the import batch.
- Duration and date display use available media/filesystem metadata and show a clear fallback when absent.
- Filters and sorting can be combined without losing the selected row unexpectedly.
- Selecting a recording shows its metadata in the side panel; selecting another updates the panel.
- The untranscribed hue is subtle and status remains understandable without color.
- Reopening the app preserves the catalog.

## Automated test checklist

- Test supported and unsupported import behavior.
- Test display metadata fallbacks and duration formatting.
- Test filtering by status and duration, including combined filters.
- Test sorting for every displayed column.
- Test selection updates the details panel.
- Test persistence across application restart at the storage layer.

## User-run checklist

- Import a short recording, a long recording, and several files at once.
- Confirm the displayed filename, duration, and date look right.
- Filter to untranscribed recordings, under 10 minutes, and over 40 minutes; combine filters.
- Sort each column in both directions.
- Select several rows and confirm the side panel follows the selection.
- Close and reopen the app and confirm imported recordings remain listed.
- Try an unsupported file and confirm the app explains the problem while keeping valid imports.
