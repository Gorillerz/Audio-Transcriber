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
  output_format: "text" | "json";
}

export interface PipelineConfig {
  name: string;
  description: string;
  steps: PipelineStep[];
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

export interface RawTranscript {
  id: string;
  recording_id: string;
  version: number;
  content: string;
  created_at: string;
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
  stages: PipelineStageRun[];
}

export interface ImportItem {
  recording: Recording;
  duplicate: boolean;
  possible_matches: Array<Pick<Recording, "id" | "original_name" | "size_bytes" | "duration_seconds">>;
}
