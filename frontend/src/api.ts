/** Thin typed client for the local FastAPI catalog. */
import type { HistoricalOutput, ImportItem, OfficialOutput, OpenRouterModel, PipelineConfig, PipelineRun, RawTranscript, Recording, RecordingGroup, RecordingPipelineRun, RecordingWaveform, SavedPipeline, TranscriptionModel, TranscriptionProvider, TranscriptionRun } from "./types";

export type OpenRouterKeyStatus = { configured: boolean; source: string };
let openRouterModelsPromise: Promise<OpenRouterModel[]> | null = null;

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

/** Load the cached or generated amplitude envelope for one recording. */
export async function fetchRecordingWaveform(id: string): Promise<RecordingWaveform> {
  return checked(await fetch(`/api/recordings/${id}/waveform`));
}

/** Read key availability and source without requesting the secret itself. */
export async function fetchOpenRouterKeyStatus(): Promise<OpenRouterKeyStatus> {
  return checked(await fetch("/api/settings/openrouter"));
}

/** Fetch the model catalog once per browser session and share concurrent requests. */
export function fetchOpenRouterModels(): Promise<OpenRouterModel[]> {
  if (!openRouterModelsPromise) {
    openRouterModelsPromise = fetch("/api/openrouter/models").then((response) => checked<OpenRouterModel[]>(response)).catch((error) => {
      openRouterModelsPromise = null;
      throw error;
    });
  }
  return openRouterModelsPromise;
}

/** Store the provided key in the operating system's credential store. */
export async function saveOpenRouterKey(apiKey: string): Promise<OpenRouterKeyStatus> {
  return checked(await fetch("/api/settings/openrouter", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: apiKey }) }));
}

/** Remove the saved key while allowing an environment variable fallback. */
export async function deleteOpenRouterKey(): Promise<OpenRouterKeyStatus> {
  return checked(await fetch("/api/settings/openrouter", { method: "DELETE" }));
}

/** Validate a typed key or configured key with OpenRouter without saving it. */
export async function testOpenRouterKey(apiKey?: string): Promise<{ valid: boolean; message: string }> {
  return checked(await fetch("/api/settings/openrouter/test", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ api_key: apiKey || null }) }));
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

/** Load saved pipeline runs and stage outputs for a recording, newest first. */
export async function fetchRecordingPipelineRuns(id: string): Promise<RecordingPipelineRun[]> {
  try {
    return await checked(await fetch(`/api/recordings/${id}/pipeline-runs`));
  } catch (error) {
    // Older local API processes return FastAPI's generic 404 because they predate this focused endpoint.
    if (!(error instanceof Error) || !["Not Found", "Request failed (404)"].includes(error.message)) throw error;
    const recentRuns = await fetchPipelineRuns();
    const fullRuns = await Promise.all(recentRuns.map(async (run) => {
      try { return await fetchPipelineRun(run.id); } catch { return null; }
    }));
    return fullRuns.filter((run): run is PipelineRun => Boolean(run?.stages.some((stage) => stage.recording_id === id)))
      .map((run) => ({
        id: run.id,
        pipeline_name: run.pipeline_name,
        status: run.status,
        created_at: run.created_at,
        finished_at: run.finished_at,
        stages: run.stages.filter((stage) => stage.recording_id === id).map((stage) => ({
          id: stage.id,
          step_name: stage.step_name,
          step_index: stage.step_index,
          provider: stage.provider,
          model: stage.model,
          status: stage.status,
          output_text: stage.output_text,
          error: stage.error,
          started_at: stage.started_at,
          finished_at: stage.finished_at,
        })),
      }));
  }
}

/** Fetch outputs that are currently official for this recording. */
export async function fetchOfficialOutputs(id: string): Promise<OfficialOutput[]> {
  return checked(await fetch(`/api/recordings/${id}/outputs`));
}

/** Fetch replaced and removed outputs for the recording's previous-versions archive. */
export async function fetchOutputHistory(id: string): Promise<HistoricalOutput[]> {
  return checked(await fetch(`/api/recordings/${id}/output-history`));
}

/** Move an official output into its durable history rather than deleting its content. */
export async function archiveOfficialOutput(recordingId: string, outputId: string): Promise<HistoricalOutput> {
  return checked(await fetch(`/api/recordings/${recordingId}/outputs/${outputId}`, { method: "DELETE" }));
}

/** Change an output's order; transcription is pinned by the backend. */
export async function moveOfficialOutput(recordingId: string, outputId: string, direction: "up" | "down"): Promise<OfficialOutput[]> {
  return checked(await fetch(`/api/recordings/${recordingId}/outputs/${outputId}/order`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ direction }),
  }));
}

/** Rename one official output; the backend enforces per-recording uniqueness. */
export async function renameOfficialOutput(recordingId: string, outputId: string, name: string): Promise<OfficialOutput> {
  return checked(await fetch(`/api/recordings/${recordingId}/outputs/${outputId}/name`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }),
  }));
}

/** Restore archived text as a new official output, optionally under a conflict-free name. */
export async function restoreHistoricalOutput(recordingId: string, historyId: string, outputName?: string): Promise<OfficialOutput> {
  return checked(await fetch(`/api/recordings/${recordingId}/output-history/${historyId}/restore`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ output_name: outputName ?? null }),
  }));
}

/** Save a new immutable raw transcript version for a recording. */
export async function saveRawTranscript(id: string, content: string): Promise<RawTranscript> {
  return checked(await fetch(`/api/recordings/${id}/transcripts`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }) }));
}

/** Check local ASR provider readiness and return the estimate for this file. */
export async function fetchTranscriptionProviders(recordingId: string): Promise<TranscriptionProvider[]> {
  return checked(await fetch(`/api/transcription/providers?recording_id=${encodeURIComponent(recordingId)}`));
}

/** Load selectable local ASR models without triggering the WSL GPU preflight. */
export async function fetchTranscriptionModels(): Promise<TranscriptionModel[]> {
  return checked(await fetch("/api/transcription/models"));
}

/** Start one local transcription job and return its persistent run ID. */
export async function startTranscription(recordingId: string, provider = "wsl-whisper"): Promise<TranscriptionRun> {
  return checked(await fetch(`/api/recordings/${recordingId}/transcriptions`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider }),
  }));
}

/** Poll a local transcription run for progress, failure, or its saved result. */
export async function fetchTranscriptionRun(runId: string): Promise<TranscriptionRun> {
  return checked(await fetch(`/api/transcriptions/${runId}`));
}

/** Restore the latest transcription state when opening a recording again. */
export async function fetchLatestTranscription(recordingId: string): Promise<TranscriptionRun | null> {
  return checked(await fetch(`/api/recordings/${recordingId}/transcriptions/latest`));
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
export async function fetchPipelineRun(id: string, includeInputs = false): Promise<PipelineRun> {
  return checked(await fetch(`/api/pipeline-runs/${id}${includeInputs ? "?include_inputs=true" : ""}`));
}

/** Retry failed pipeline stages while preserving completed stage outputs. */
export async function retryPipelineRun(id: string): Promise<PipelineRun> {
  return checked(await fetch(`/api/pipeline-runs/${id}/retry`, { method: "POST" }));
}
