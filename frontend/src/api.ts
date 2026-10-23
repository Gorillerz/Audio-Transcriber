/** Thin typed client for the local FastAPI catalog. */
import type { ImportItem, PipelineConfig, PipelineRun, RawTranscript, Recording, RecordingGroup, SavedPipeline } from "./types";

/** Parse API failures into readable messages for the user-facing toast. */
async function checked<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

/** Fetch the current recording catalog. */
export async function fetchRecordings(): Promise<Recording[]> {
  return checked(await fetch("/api/recordings"));
}

/** Fetch saved group definitions and counts for the sidebar and group picker. */
export async function fetchGroups(): Promise<RecordingGroup[]> {
  return checked(await fetch("/api/groups"));
}

/** Create a group and place the supplied recordings in it. */
export async function createGroup(name: string, recordingIds: string[]): Promise<RecordingGroup> {
  return checked(await fetch("/api/groups", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, recording_ids: recordingIds }) }));
}

/** Add selected recordings to an existing group. */
export async function addToGroup(groupId: string, recordingIds: string[]): Promise<RecordingGroup> {
  return checked(await fetch(`/api/groups/${groupId}/recordings`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ recording_ids: recordingIds }) }));
}

/** Upload the selected recordings as a batch to the local catalog. */
export async function importFiles(files: File[]): Promise<{ imported: ImportItem[]; errors: Array<{ name: string; error: string }> }> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file, file.name));
  return checked(await fetch("/api/recordings/import", { method: "POST", body: form }));
}

/** Confirm that a metadata-similar file is a distinct recording. */
export async function confirmSeparate(id: string): Promise<Recording> {
  return checked(await fetch(`/api/recordings/${id}/confirm-separate`, { method: "POST" }));
}

/** Attach a changed-byte file as an alias of a recording after user confirmation. */
export async function confirmMatch(id: string, canonicalId: string): Promise<Recording> {
  return checked(await fetch(`/api/recordings/${id}/confirm-match/${canonicalId}`, { method: "POST" }));
}

/** Save a user's known transcription status for legacy recordings. */
export async function updateStatus(id: string, status: Recording["status"]): Promise<Recording> {
  return checked(await fetch(`/api/recordings/${id}/status`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status }),
  }));
}

/** Move a confirmed set of recordings into the operating system's trash. */
export async function deleteRecordings(ids: string[]): Promise<{ deleted: string[]; errors: Array<{ id: string; error: string }> }> {
  return checked(await fetch("/api/recordings", {
    method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ids }),
  }));
}

/** Read all saved versions of a recording's raw transcript. */
export async function fetchRawTranscripts(id: string): Promise<RawTranscript[]> {
  return checked(await fetch(`/api/recordings/${id}/transcripts`));
}

/** Save a new immutable raw transcript version for a recording. */
export async function saveRawTranscript(id: string, content: string): Promise<RawTranscript> {
  return checked(await fetch(`/api/recordings/${id}/transcripts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }) }));
}

/** Fetch pipeline names and revisions for the editor and run dialog. */
export async function fetchPipelines(): Promise<SavedPipeline[]> {
  return checked(await fetch("/api/pipelines"));
}

/** Load the complete editable configuration for one saved pipeline. */
export async function fetchPipeline(id: string): Promise<SavedPipeline> {
  return checked(await fetch(`/api/pipelines/${id}`));
}

/** Create a pipeline or save a new revision to an existing one. */
export async function savePipeline(config: PipelineConfig, id?: string): Promise<SavedPipeline> {
  return checked(await fetch(id ? `/api/pipelines/${id}` : "/api/pipelines", { method: id ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(config) }));
}

/** Make an independent copy of a saved pipeline. */
export async function duplicatePipeline(id: string): Promise<SavedPipeline> {
  return checked(await fetch(`/api/pipelines/${id}/duplicate`, { method: "POST" }));
}

/** Queue a saved pipeline for the selected recordings. */
export async function startPipelineRun(id: string, recordingIds: string[]): Promise<PipelineRun> {
  return checked(await fetch(`/api/pipelines/${id}/runs`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ recording_ids: recordingIds }) }));
}

/** Read the latest run statuses for display and polling. */
export async function fetchPipelineRuns(): Promise<Array<{ id: string; pipeline_name: string; status: string; created_at: string; total_stages: number; succeeded_stages: number; failed_stages: number }>> {
  return checked(await fetch("/api/pipeline-runs"));
}

/** Read full per-recording and per-step outputs for one run. */
export async function fetchPipelineRun(id: string): Promise<PipelineRun> {
  return checked(await fetch(`/api/pipeline-runs/${id}`));
}

/** Retry failed pipeline stages while preserving completed stage outputs. */
export async function retryPipelineRun(id: string): Promise<PipelineRun> {
  return checked(await fetch(`/api/pipeline-runs/${id}/retry`, { method: "POST" }));
}
