# MVP1 — Audio library

## Goal

Create the first useful screen: a catalog of audio recordings with a clear selection and metadata view. Keep the layout easy to adjust before adding transcription workflows.

## Included

- Import one or more local audio files through a button and drag-and-drop.
- Assign each imported recording a stable ID and content hash so repeated imports and filename changes can be recognized. If the hash differs, show metadata-based matches as candidates for confirmation.
- Show recordings in a table with name, explicit duration units (for example `1s` or `1h 23m 4s`), embedded recording date, group names, and transcription status.
- Display “Unknown date” when no embedded recording date is available; never substitute the file's import or modification time for its recording date.
- Derive the status from transcript data associated with the catalog entry. If no known transcript is linked, show untranscribed; metadata-only matches remain candidates until confirmed.
- Let the user manually mark a pre-existing recording as transcribed while legacy transcript files are not yet linked. Make clear that the transcript file itself is not imported and allow the status to be corrected.
- Give untranscribed recordings a subtle background hue and a text/icon status so color is not the only signal.
- Filter by transcription status and duration ranges, including under 10 minutes and over 40 minutes.
- Sort the recording, duration, recording-date, and transcription-status columns.
- Create named recording groups, add selected recordings to new or existing groups, and filter the catalog from the sidebar by group.
- Display assigned group names in the table, or a dash when a recording has no group.
- Move one recording or a selected batch to the operating system trash after a warning and confirmation.
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
- Duration and embedded recording date display use audio metadata and show a clear fallback when absent; file import time is shown separately in details.
- Filters and sorting can be combined without losing the selected row unexpectedly.
- Selecting a recording shows its metadata in the side panel; selecting another updates the panel.
- The untranscribed hue is subtle and status remains understandable without color.
- Reopening the app preserves the catalog.
- Manually marking a legacy recording as transcribed persists across refresh and can be corrected.
- Group definitions and memberships persist across refresh; group sidebar counts match their current members.
- Confirming deletion moves source audio to the operating system trash and removes the recording from the catalog; a failed move keeps its catalog entry.

## Automated test checklist

- Test supported and unsupported import behavior.
- Test display metadata fallbacks and duration formatting.
- Test filtering by status and duration, including combined filters.
- Test sorting for every displayed column.
- Test selection updates the details panel.
- Test persistence across application restart at the storage layer.
- Test group creation, membership persistence, and group counts.
- Test that successful trash moves remove catalog rows and failed moves retain them.

## User-run checklist

- Import a short recording, a long recording, and several files at once.
- Confirm the displayed filename, duration, and date look right.
- Filter to untranscribed recordings, under 10 minutes, and over 40 minutes; combine filters.
- Sort each column in both directions.
- Select several rows and confirm the side panel follows the selection.
- Mark one known legacy recording as transcribed, filter by each status, and correct the status again.
- Close and reopen the app and confirm imported recordings remain listed.
- Select multiple recordings, create a named group, and confirm it appears in the sidebar with the right count.
- Select recordings and add them to an existing group; click the group and confirm only its recordings appear.
- Confirm the Group column lists each assigned group and shows a dash for ungrouped recordings.
- Select one recording and then several recordings, confirm each delete warning, and verify files are in the Recycle Bin and absent from the catalog.
- Try an unsupported file and confirm the app explains the problem while keeping valid imports.
