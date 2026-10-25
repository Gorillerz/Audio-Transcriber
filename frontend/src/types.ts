/** Shared shapes returned by the local catalog API. */
export interface Recording {
  id: string;
  original_name: string;
  stored_path: string;
  sha256: string;
  size_bytes: number;
  duration_seconds: number | null;
  media_date: string | null;
  imported_at: string;
  mime_type: string | null;
  extension: string;
  status: "untranscribed" | "transcribed";
  status_source: "derived" | "manual";
  possible_match_id: string | null;
  alias_count: number;
  group_ids: string[];
  aliases?: Array<{ original_name: string; sha256: string; size_bytes: number; added_at: string }>;
}

/** Compact amplitude envelope used to draw a seekable waveform without loading full PCM into the browser. */
export interface RecordingWaveform {
  recording_id: string;
  duration_seconds: number | null;
  sample_rate: number;
  peaks: number[];
}

export interface RecordingGroup {
  id: string;
  name: string;
  recording_count: number;
}

export interface PipelineStep {
  id: string;
  name: string;
  kind: string;
  model: string;
  prompt: string;
  input_ref: string;
}

export interface PipelineConfig {
  name: string;
  description: string;
  initial_output_name?: string;
  steps: PipelineStep[];
}

/** One Whisper-recognized word with its media time and optional confidence score. */
export interface TimedTranscriptWord {
  start: number;
  end: number;
  text: string;
  probability?: number | null;
}

/** Whisper alignment linked to the exact immutable raw transcript version. */
export interface TranscriptWordAlignment {
  transcript_id: string;
  words: TimedTranscriptWord[];
}

/** A named output currently promoted as the recording's official version. */
export interface OfficialOutput {
  id: string;
  recording_id: string;
  name: string;
  kind: string;
  content: string;
  provider: string;
  model: string;
  run_id: string | null;
  stage_run_id: string | null;
  source_id: string | null;
  created_at: string;
  position: number;
  word_alignment?: TranscriptWordAlignment | null;
}

/** A replaced or removed official output retained for inspection and restore. */
export interface HistoricalOutput extends OfficialOutput {
  archived_at: string;
  archive_reason: "replaced" | "removed" | string;
}

export interface SavedPipeline {
  id: string;
  name: string;
  description: string;
  version: number;
  created_at: string;
  updated_at: string;
  config?: PipelineConfig;
  steps?: PipelineStep[];
}

/** Display fields used by the OpenRouter model autocomplete. Prices are USD per million tokens. */
export interface OpenRouterModel {
  id: string;
  name: string;
  publisher: string;
  created: number;
  input_cost_per_million: number | null;
  output_cost_per_million: number | null;
}

export interface RawTranscript {
  id: string;
  recording_id: string;
  version: number;
  content: string;
  created_at: string;
  provider: string;
  model: string;
}

/** Local transcription provider details and benchmark estimate shown before launch. */
export interface TranscriptionProvider {
  id: string;
  name: string;
  provider: string;
  model: string;
  available: boolean;
  gpu_name: string | null;
  timing: string;
  languages: string;
  estimated_seconds: number | null;
  estimate_note: string;
  reason: string | null;
}

/** Supported local ASR model choices shown in transcription stages. */
export interface TranscriptionModel {
  id: string;
  name: string;
  provider: string;
  timing: string;
  languages: string;
}

/** Persistent local ASR job state returned by the transcription API. */
export interface TranscriptionRun {
  id: string;
  recording_id: string;
  provider: string;
  model: string;
  device: string;
  status: "running" | "succeeded" | "failed";
  started_at: string;
  finished_at: string | null;
  elapsed_seconds: number;
  estimated_seconds?: number;
  gpu_name?: string;
  error: string | null;
  result: { text: string; language: string | null; words: TimedTranscriptWord[]; transcript_id: string } | null;
}

export interface PipelineStageRun {
  id: string;
  recording_id: string;
  original_name: string;
  step_id: string;
  step_name: string;
  step_index: number;
  provider: string;
  model: string;
  prompt: string;
  prompt_hash: string;
  input_ref: string;
  output_format: string;
  status: "queued" | "running" | "succeeded" | "failed";
  input_text: string | null;
  output_text: string | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface PipelineRun {
  id: string;
  pipeline_id: string;
  pipeline_name: string;
  status: "queued" | "running" | "succeeded" | "failed";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  pipeline_snapshot: PipelineConfig & { pipeline_id: string; pipeline_version: number };
  inputs: Array<{ recording_id: string; raw_version: number; raw_content: string; source_output_id?: string | null; source_output_name?: string; original_name: string }>;
  stages: PipelineStageRun[];
}

/** Compact saved outputs shown for one recording in its details panel. */
export interface RecordingPipelineRun {
  id: string;
  pipeline_name: string;
  status: "queued" | "running" | "succeeded" | "failed";
  created_at: string;
  finished_at: string | null;
  stages: Array<Pick<PipelineStageRun, "id" | "step_name" | "step_index" | "provider" | "model" | "status" | "output_text" | "error" | "started_at" | "finished_at">>;
}

export interface ImportItem {
  recording: Recording;
  duplicate: boolean;
  possible_matches: Array<Pick<Recording, "id" | "original_name" | "size_bytes" | "duration_seconds">>;
}
