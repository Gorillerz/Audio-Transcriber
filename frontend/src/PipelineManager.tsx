/** Pipeline editor and run monitor for local transcription and OpenRouter workflows. */
import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Copy, Plus, Play, Save, X } from "lucide-react";
import { formatDuration } from "./catalog";
import { duplicatePipeline, fetchOfficialOutputs, fetchOpenRouterModels, fetchPipeline, fetchPipelineRun, fetchPipelineRuns, fetchPipelines, fetchRecordings, fetchTranscriptionModels, retryPipelineRun, savePipeline, startPipelineRun } from "./api";
import type { OfficialOutput, OpenRouterModel, PipelineConfig, PipelineRun, PipelineStep, Recording, SavedPipeline, TranscriptionModel } from "./types";

const newStep = (): PipelineStep => ({ id: crypto.randomUUID(), name: "Cleanup", kind: "cleanup", model: "", prompt: "Clean up the transcript while preserving its meaning and language.", input_ref: "raw" });

type RecordingQueueItem = {
  id: string;
  original_name: string;
  duration_seconds: number | null;
  status: "ready" | "queued" | "processing" | "completed" | "failed";
};

/** Estimate model tokens from character count; exact counts depend on the selected model tokenizer. */
function approximateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

/** Estimate transcript tokens from audio length when a pipeline begins with local ASR. */
function estimatedSpeechTokens(durationSeconds: number): number {
  return Math.ceil((durationSeconds / 60) * 150 * 1.3);
}

/** Apply the requested typical output sizes to each stage kind. */
function estimatedOutputTokens(kind: string, rawTokens: number, inputTokens: number): number {
  if (kind === "cleanup" || kind === "verification") return Math.ceil(rawTokens * 0.9);
  if (kind === "summary") return Math.ceil(500 * 1.3);
  if (kind === "title") return Math.ceil(10 * 1.3);
  return Math.ceil(inputTokens * 0.9);
}

/** Format an aggregate USD estimate while retaining useful precision for small requests. */
function formatEstimatedCost(amount: number | null): string {
  if (amount === null) return "—";
  if (amount > 0 && amount < 0.001) return "<0.001";
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 6 }).format(amount);
}

/** Display embedded recording date metadata with its local time. */
function formatRecordedTime(value: string | null | undefined): string {
  if (!value) return "Unknown";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  }).format(date);
}

/** Edit reusable stage chains, launch selected recordings, and review saved run outputs. */
export default function PipelineManager({ open, recordingIds, onClose }: { open: boolean; recordingIds: string[]; onClose: () => void }) {
  const [pipelines, setPipelines] = useState<SavedPipeline[]>([]);
  const [pipelineId, setPipelineId] = useState("");
  const [config, setConfig] = useState<PipelineConfig>({ name: "New pipeline", description: "", initial_output_name: "Transcription", steps: [newStep()] });
  const [runs, setRuns] = useState<Array<{ id: string; pipeline_name: string; status: string; created_at: string; total_stages: number; succeeded_stages: number; failed_stages: number }>>([]);
  const [simulationRuns, setSimulationRuns] = useState<PipelineRun[]>([]);
  const [activeRun, setActiveRun] = useState<PipelineRun | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [models, setModels] = useState<OpenRouterModel[]>([]);
  const [modelsError, setModelsError] = useState("");
  const [transcriptionModels, setTranscriptionModels] = useState<TranscriptionModel[]>([]);
  const [transcriptionModelsError, setTranscriptionModelsError] = useState("");
  const [flowPanelWidth, setFlowPanelWidth] = useState(620);
  const resizeStart = useRef<{ x: number; width: number } | null>(null);
  const [workflowPage, setWorkflowPage] = useState<"pipeline" | "run">("pipeline");
  const [flowRecordingId, setFlowRecordingId] = useState("");
  const [manualQueueSelection, setManualQueueSelection] = useState(false);
  const [officialOutputsByRecording, setOfficialOutputsByRecording] = useState<Record<string, OfficialOutput[]>>({});
  const [selectedRecordings, setSelectedRecordings] = useState<Recording[]>([]);
  const recordingKey = recordingIds.join("|");
  const recentRuns = [
    ...runs,
    ...simulationRuns.map((run) => ({
      id: run.id,
      pipeline_name: `${run.pipeline_name} · Simulation`,
      status: run.status,
      created_at: run.created_at,
      total_stages: run.stages.length,
      succeeded_stages: run.stages.filter((stage) => stage.status === "succeeded").length,
      failed_stages: run.stages.filter((stage) => stage.status === "failed").length,
    })),
  ].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));

  /** Load reusable definitions and recent runs whenever the modal opens. */
  useEffect(() => { if (open) { setWorkflowPage("pipeline"); setManualQueueSelection(false); void refresh().then((saved) => { if (!pipelineId && saved.length) void loadPipeline(saved[0].id); }); } }, [open]);
  useEffect(() => {
    if (!open) return;
    void fetchOpenRouterModels().then((items) => { setModels(items); setModelsError(""); })
      .catch((error: Error) => setModelsError(error.message));
  }, [open]);
  useEffect(() => {
    if (!open) return;
    void fetchTranscriptionModels().then((items) => { setTranscriptionModels(items); setTranscriptionModelsError(""); })
      .catch((error: Error) => setTranscriptionModelsError(error.message));
  }, [open]);
  useEffect(() => {
    if (!open || recordingIds.length === 0) {
      setOfficialOutputsByRecording({}); setSelectedRecordings([]);
      return;
    }
    let current = true;
    void Promise.all([
      fetchRecordings().catch(() => []),
      Promise.all(recordingIds.map((id) => fetchOfficialOutputs(id).catch(() => []))),
    ]).then(([catalog, officialOutputs]) => {
      if (!current) return;
      const byId = new Map(catalog.map((recording) => [recording.id, recording]));
      setSelectedRecordings(recordingIds.map((id) => byId.get(id)).filter((recording): recording is Recording => Boolean(recording)));
      setOfficialOutputsByRecording(Object.fromEntries(recordingIds.map((id, index) => [id, officialOutputs[index]])));
      setFlowRecordingId((currentId) => recordingIds.includes(currentId) ? currentId : recordingIds[0]);
    });
    return () => { current = false; };
  }, [open, recordingKey]);

  const initialOutputName = config.initial_output_name ?? "Transcription";
  const commonInitialOutputs = recordingIds.length && recordingIds.every((id) => officialOutputsByRecording[id])
    ? (officialOutputsByRecording[recordingIds[0]] ?? []).filter((output) => recordingIds.every((id) =>
      (officialOutputsByRecording[id] ?? []).some((candidate) => candidate.name.toLocaleLowerCase() === output.name.toLocaleLowerCase())))
      .sort((left, right) => Number(right.kind === "transcription") - Number(left.kind === "transcription") || left.name.localeCompare(right.name))
    : [];
  const isAsrPipeline = config.steps[0]?.kind === "transcription";
  const selectedInputsAvailable = isAsrPipeline || recordingIds.length > 0 && recordingIds.every((id) => {
    const outputs = officialOutputsByRecording[id] ?? [];
    return outputs.some((output) => output.kind === "transcription")
      && outputs.some((output) => output.name.toLocaleLowerCase() === initialOutputName.toLocaleLowerCase());
  });

  const usageEstimates = config.steps.map((step) => ({
    step,
    inputTokens: 0,
    outputTokens: 0,
    audioSeconds: 0,
    inputCost: 0,
    outputCost: 0,
    costKnown: true,
  }));
  const hasTranscriptionStage = config.steps[0]?.kind === "transcription";
  let transcriptsAvailable = 0;
  const perRecordingEstimates = recordingIds.map((recordingId) => {
    const recording = selectedRecordings.find((item) => item.id === recordingId);
    const selectedSource = (officialOutputsByRecording[recordingId] ?? []).find((output) => output.name.toLocaleLowerCase() === initialOutputName.toLocaleLowerCase());
    const rawTokens = hasTranscriptionStage && recording?.duration_seconds != null
      ? estimatedSpeechTokens(recording.duration_seconds)
      : selectedSource ? approximateTokens(selectedSource.content) : null;
    if (rawTokens == null) return { recordingId, cost: null as number | null };
    transcriptsAvailable += 1;
    let cost = 0;
    let costKnown = true;
    const priorOutputs = new Map<string, number>();
    config.steps.forEach((step, index) => {
      if (step.kind === "transcription") {
        const estimate = usageEstimates[index];
        estimate.audioSeconds += recording?.duration_seconds ?? 0;
        estimate.outputTokens += rawTokens;
        priorOutputs.set(step.id, rawTokens);
        return;
      }
      const sourceTokens = step.input_ref === "raw" ? rawTokens : priorOutputs.get(step.input_ref) ?? rawTokens;
      const inputTokens = approximateTokens(step.prompt) + sourceTokens;
      const outputTokens = estimatedOutputTokens(step.kind, rawTokens, sourceTokens);
      const estimate = usageEstimates[index];
      estimate.inputTokens += inputTokens;
      estimate.outputTokens += outputTokens;
      priorOutputs.set(step.id, outputTokens);
      const model = models.find((item) => item.id === step.model);
      if (!model || model.input_cost_per_million === null || model.output_cost_per_million === null) {
        estimate.costKnown = false;
        costKnown = false;
      } else {
        const inputCost = inputTokens * model.input_cost_per_million / 1_000_000;
        const outputCost = outputTokens * model.output_cost_per_million / 1_000_000;
        estimate.inputCost += inputCost;
        estimate.outputCost += outputCost;
        cost += inputCost + outputCost;
      }
    });
    return { recordingId, cost: costKnown ? cost : null };
  });
  const totalEstimatedCost = transcriptsAvailable > 0 && perRecordingEstimates.every((item) => item.cost !== null)
    ? perRecordingEstimates.reduce((total, item) => total + (item.cost ?? 0), 0)
    : null;
  const runInputIds = activeRun?.inputs?.map((input) => input.recording_id) ?? [];
  const runStageIds = activeRun?.stages.map((stage) => stage.recording_id) ?? [];
  const runRecordingIds = [...new Set([...runInputIds, ...runStageIds])];
  const queueRecordings = activeRun && runRecordingIds.length
    ? runRecordingIds.map((id) => {
      const input = activeRun.inputs.find((item) => item.recording_id === id);
      const stage = activeRun.stages.find((item) => item.recording_id === id);
      const recording = selectedRecordings.find((item) => item.id === id);
      return {
        id,
        original_name: input?.original_name ?? stage?.original_name ?? recording?.original_name ?? "Recording",
        duration_seconds: recording?.duration_seconds ?? null,
      };
    })
    : recordingIds.map((id) => {
      const recording = selectedRecordings.find((item) => item.id === id);
      return { id, original_name: recording?.original_name ?? "Recording", duration_seconds: recording?.duration_seconds ?? null };
    });
  const queueItems = queueRecordings.map((recording) => {
    const stages = activeRun?.stages.filter((stage) => stage.recording_id === recording.id) ?? [];
    const status: RecordingQueueItem["status"] = !activeRun ? "ready"
      : stages.some((stage) => stage.status === "running") ? "processing"
        : stages.some((stage) => stage.status === "failed") ? "failed"
          : (stages.length > 0 && stages.every((stage) => stage.status === "succeeded")) || activeRun.status === "succeeded" ? "completed" : "queued";
    return { ...recording, status };
  });
  const processingRecordingId = activeRun?.stages.find((stage) => stage.status === "running")?.recording_id;
  const failedRecordingId = queueItems.find((item) => item.status === "failed")?.id;
  const queuedRecordingId = queueItems.find((item) => item.status === "queued")?.id;
  const currentRunRecordingId = processingRecordingId
    ?? (activeRun && ["queued", "running"].includes(activeRun.status) ? queuedRecordingId : failedRecordingId)
    ?? (queueItems.some((item) => item.id === flowRecordingId) ? flowRecordingId : queueItems[0]?.id ?? "");
  const focusRecordingId = manualQueueSelection && queueItems.some((item) => item.id === flowRecordingId)
    ? flowRecordingId
    : currentRunRecordingId;
  useEffect(() => {
    if (!activeRun || manualQueueSelection) return;
    if (currentRunRecordingId && currentRunRecordingId !== flowRecordingId) setFlowRecordingId(currentRunRecordingId);
  }, [activeRun?.id, activeRun?.status, activeRun?.stages, currentRunRecordingId, flowRecordingId, manualQueueSelection]);

  /** Refresh picker lists without changing the active editor values. */
  async function refresh(): Promise<SavedPipeline[]> {
    try {
      const [saved, recent] = await Promise.all([fetchPipelines(), fetchPipelineRuns()]);
      setPipelines(saved); setRuns(recent);
      return saved;
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not load workflows."); return []; }
  }

  /** Fill the form from an immutable saved pipeline revision. */
  async function loadPipeline(id: string): Promise<void> {
    try {
      const item = await fetchPipeline(id);
      setPipelineId(id); setConfig(item.config ?? { name: item.name, description: item.description, initial_output_name: "Transcription", steps: [] }); setMessage("");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not load pipeline."); }
  }

  /** Persist current fields as a new pipeline or an incremented revision. */
  async function save(): Promise<void> {
    setBusy(true);
    try {
      const saved = await savePipeline(config, pipelineId || undefined);
      setPipelineId(saved.id); setConfig(saved.config ?? config); setMessage(`Saved version ${saved.version}.`); await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not save pipeline."); }
    finally { setBusy(false); }
  }

  /** Copy the current saved pipeline so edits do not change its earlier definition. */
  async function duplicate(): Promise<void> {
    if (!pipelineId) return;
    try { const copy = await duplicatePipeline(pipelineId); await refresh(); await loadPipeline(copy.id); setMessage("Pipeline duplicated."); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not duplicate pipeline."); }
  }

  /** Start a single or batch run using the configured official output as its frozen input. */
  async function run(): Promise<void> {
    if (!pipelineId || !recordingIds.length) return;
    setBusy(true);
    try {
      setActiveRun(null); setManualQueueSelection(false);
      const created = await startPipelineRun(pipelineId, recordingIds);
      setActiveRun(created); setFlowRecordingId(created.inputs?.[0]?.recording_id ?? recordingIds[0]); setWorkflowPage("run"); setMessage("Pipeline queued."); await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not start pipeline."); }
    finally { setBusy(false); }
  }

  /** Poll the persisted run record while its stages are queued or running. */
  useEffect(() => {
    if (!activeRun || activeRun.pipeline_id === "simulation" || !["queued", "running"].includes(activeRun.status)) return;
    const timer = window.setInterval(() => { void fetchPipelineRun(activeRun.id).then((fresh) => setActiveRun((current) => ({ ...fresh, inputs: fresh.inputs?.length ? fresh.inputs : current?.inputs ?? [] }))).catch(() => undefined); }, 1200);
    return () => window.clearInterval(timer);
  }, [activeRun?.id, activeRun?.status]);

  useEffect(() => {
    if (!activeRun || activeRun.pipeline_id === "simulation" || !["succeeded", "failed"].includes(activeRun.status)) return;
    for (const recordingId of new Set(activeRun.stages.filter((stage) => stage.status === "succeeded").map((stage) => stage.recording_id))) {
      window.dispatchEvent(new CustomEvent("journal:official-outputs-updated", { detail: { recordingId } }));
    }
  }, [activeRun?.id, activeRun?.status]);

  /** Retry only failed stages while completed stage results remain stored. */
  async function retry(): Promise<void> {
    if (!activeRun) return;
    try { setActiveRun(await retryPipelineRun(activeRun.id)); setMessage("Failed stages queued for retry."); await refresh(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not retry run."); }
  }

  /** Animate a local pass-through simulation without contacting OpenRouter. */
  async function simulate(): Promise<void> {
    const recordingId = recordingIds[0];
    if (!recordingId || !config.steps.length) return;
    if (config.steps.some((step) => step.kind === "transcription")) {
      setMessage("Local transcription uses the audio model and cannot be simulated as a text-only pipeline stage.");
      return;
    }
    const recordingName = selectedRecordings.find((recording) => recording.id === recordingId)?.original_name ?? "Selected recording";
    setBusy(true); setMessage("Simulating locally. No OpenRouter requests will be made.");
    try {
      const availableOutputs = officialOutputsByRecording[recordingId] ?? [];
      if (!availableOutputs.some((output) => output.kind === "transcription")) throw new Error("This recording has no official transcription. Transcribe it before simulating text stages.");
      const inputOutput = availableOutputs.find((output) => output.name.toLocaleLowerCase() === initialOutputName.toLocaleLowerCase());
      if (!inputOutput?.content) throw new Error(`This recording has no official output named '${initialOutputName}' to simulate from.`);
      const now = new Date().toISOString();
      const runId = `simulation-${crypto.randomUUID()}`;
      const simulatedStages: PipelineRun["stages"] = config.steps.map((step, index) => ({
        id: `${runId}-${step.id}`, recording_id: recordingId, original_name: recordingName, step_id: step.id,
        step_name: step.name, step_index: index, provider: "simulation", model: step.model, prompt: step.prompt,
        prompt_hash: "simulation", input_ref: step.input_ref, output_format: "text", status: "queued",
        input_text: null, output_text: null, error: null, started_at: null, finished_at: null,
      }));
      const initialRun: PipelineRun = { id: runId, pipeline_id: "simulation", pipeline_name: config.name, status: "running", created_at: now,
        started_at: now, finished_at: null, error: null, pipeline_snapshot: { ...config, pipeline_id: pipelineId, pipeline_version: 0 },
        inputs: [{ recording_id: recordingId, raw_version: 0, raw_content: inputOutput.content, source_output_id: inputOutput.id, source_output_name: inputOutput.name, original_name: recordingName }], stages: simulatedStages };
      setActiveRun(initialRun);
      setSimulationRuns((current) => [initialRun, ...current]);
      setFlowRecordingId(recordingId);
      setManualQueueSelection(false);
      setWorkflowPage("run");
      /** Keep the temporary run history in sync so simulations can be reopened from Recent Runs. */
      const updateSimulation = (update: (run: PipelineRun) => PipelineRun) => {
        setActiveRun((current) => current?.id === runId ? update(current) : current);
        setSimulationRuns((current) => current.map((run) => run.id === runId ? update(run) : run));
      };
      const outputs = new Map<string, string>();
      for (let index = 0; index < config.steps.length; index += 1) {
        const step = config.steps[index];
        updateSimulation((current) => ({ ...current, stages: current.stages.map((stage, item) => item === index ? { ...stage, status: "running", started_at: new Date().toISOString(), input_text: step.input_ref === "raw" ? inputOutput.content : outputs.get(step.input_ref) ?? "" } : stage) }));
        await new Promise((resolve) => window.setTimeout(resolve, 850));
        const source = step.input_ref === "raw" ? inputOutput.content : outputs.get(step.input_ref) ?? "";
        const simulatedOutput = `[SIMULATED OUTPUT — no model was called]\nStage: ${step.name}\nInput source: ${step.input_ref === "raw" ? initialOutputName : config.steps.find((item) => item.id === step.input_ref)?.name ?? "Prior stage"}\n\nInput preview:\n${source.slice(0, 700)}${source.length > 700 ? "…" : ""}`;
        outputs.set(step.id, simulatedOutput);
        updateSimulation((current) => ({ ...current, stages: current.stages.map((stage, item) => item === index ? { ...stage, status: "succeeded", output_text: simulatedOutput, finished_at: new Date().toISOString() } : stage) }));
      }
      updateSimulation((current) => ({ ...current, status: "succeeded", finished_at: new Date().toISOString() }));
      setMessage("Simulation complete. No OpenRouter requests were made; the run is available in Recent Runs for this session.");
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not simulate this pipeline."); }
    finally { setBusy(false); }
  }

  /** Open a run in the flow panel and focus its first recording input. */
  async function openRun(runId: string): Promise<void> {
    setWorkflowPage("run");
    const simulation = simulationRuns.find((runItem) => runItem.id === runId);
    if (simulation) {
      setActiveRun(simulation);
      setFlowRecordingId(simulation.inputs?.[0]?.recording_id ?? simulation.stages[0]?.recording_id ?? "");
      setManualQueueSelection(false);
      return;
    }
    try {
      const run = await fetchPipelineRun(runId, true);
      // Older backend processes may omit the optional input snapshot; stage records still identify the recording.
      setActiveRun(run); setFlowRecordingId(run.inputs?.[0]?.recording_id ?? run.stages?.[0]?.recording_id ?? ""); setManualQueueSelection(false);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not load that run."); }
  }

  /** Update one step without changing the rest of the ordered pipeline. */
  function updateStep(index: number, patch: Partial<PipelineStep>): void {
    setConfig((current) => ({ ...current, steps: current.steps.map((step, item) => item === index ? { ...step, ...patch } : step) }));
  }

  /** Remove a step and rebind stages that referenced it to the raw transcript. */
  function removeStep(index: number): void {
    const removedId = config.steps[index]?.id;
    setConfig((current) => ({
      ...current,
      steps: current.steps.filter((_, item) => item !== index).map((step) => step.input_ref === removedId ? { ...step, input_ref: "raw" } : step),
    }));
  }

  /** Move a selected transcription stage to the front and refuse a duplicate. */
  function changeStepKind(index: number, kind: string): void {
    const selected = config.steps[index];
    const defaultNames: Record<string, string> = {
      transcription: "Transcription", cleanup: "Cleanup", verification: "Verification",
      summary: "Summary / topics", title: "Title", custom: "New stage",
    };
    const stageName = selected.name === defaultNames[selected.kind] || selected.name === "New stage"
      ? defaultNames[kind] ?? "New stage"
      : selected.name;
    if (kind === "transcription") {
      if (config.steps.some((step, item) => item !== index && step.kind === "transcription")) {
        setMessage("A pipeline can contain only one transcription stage.");
        return;
      }
      const model = transcriptionModels[0]?.id ?? "openai/whisper-medium";
      const transcriptionStep = { ...selected, name: stageName, kind, model, prompt: "", input_ref: "audio" };
      setConfig((current) => ({ ...current, steps: [transcriptionStep, ...current.steps.filter((_, item) => item !== index)] }));
      setMessage("The transcription stage was moved to the start of the pipeline.");
      return;
    }
    const prompts: Record<string, string> = {
      cleanup: "Clean up the transcript while preserving its meaning and language.",
      verification: "Verify the transcript follows the instructions and preserves the speaker’s meaning.",
      summary: "Summarize the main topics and key points.",
      title: "Create a concise title for this transcript.",
    };
    updateStep(index, {
      name: stageName,
      kind,
      model: selected.kind === "transcription" ? "" : selected.model,
      input_ref: selected.input_ref === "audio" ? "raw" : selected.input_ref,
      prompt: selected.kind === "transcription" ? prompts[kind] || "" : selected.prompt || prompts[kind] || "",
    });
    setMessage("");
  }

  /** Move a step and keep its output binding IDs stable for downstream steps. */
  function moveStep(index: number, offset: number): void {
    const target = index + offset;
    if (target < 0 || target >= config.steps.length) return;
    if (config.steps[index].kind === "transcription" || (target === 0 && config.steps[0].kind === "transcription")) return;
    setConfig((current) => { const steps = [...current.steps]; [steps[index], steps[target]] = [steps[target], steps[index]]; return { ...current, steps }; });
  }

  if (!open) return null;
  return <div className="workflow-overlay"><section className="workflow-window" role="dialog" aria-modal="true" aria-labelledby="workflow-title">
    <header className="workflow-header"><div><span className="workflow-eyebrow">TEXT PROCESSING</span><h2 id="workflow-title">Pipeline Workflows</h2></div><button className="icon-button" aria-label="Close workflows" onClick={onClose}><X size={18} /></button></header>
    <nav className="workflow-tabs" role="tablist" aria-label="Pipeline workflow pages">
      <button role="tab" aria-selected={workflowPage === "pipeline"} className={workflowPage === "pipeline" ? "active" : ""} onClick={() => setWorkflowPage("pipeline")}>Pipeline</button>
      <button role="tab" aria-selected={workflowPage === "run"} className={workflowPage === "run" ? "active" : ""} onClick={() => setWorkflowPage("run")}>Run{activeRun && ["queued", "running"].includes(activeRun.status) && <span className="workflow-tab-live" aria-label="Run in progress" />}</button>
    </nav>
    <div className={`workflow-body workflow-page-${workflowPage}`} style={{ "--flow-panel-width": `${flowPanelWidth}px` } as React.CSSProperties}>
      <aside className="pipeline-list"><div className="pipeline-list-title">SAVED PIPELINES</div><button className={`pipeline-option ${!pipelineId ? "selected" : ""}`} onClick={() => { setWorkflowPage("pipeline"); setPipelineId(""); setConfig({ name: "New pipeline", description: "", initial_output_name: "Transcription", steps: [newStep()] }); setActiveRun(null); }}> <Plus size={15} /> New pipeline</button>{pipelines.map((pipeline) => <button key={pipeline.id} className={`pipeline-option ${pipeline.id === pipelineId ? "selected" : ""}`} onClick={() => { setWorkflowPage("pipeline"); void loadPipeline(pipeline.id); setActiveRun(null); }}><span>{pipeline.name}</span><small>v{pipeline.version}</small></button>)}<div className="pipeline-list-title recent-title">RECENT RUNS</div>{recentRuns.slice(0, 8).map((runItem) => <button key={runItem.id} className={`run-option ${activeRun?.id === runItem.id ? "selected" : ""}`} onClick={() => void openRun(runItem.id)}><span>{runItem.pipeline_name}</span><small>{runItem.status} · {runItem.succeeded_stages}/{runItem.total_stages}</small></button>)}</aside>
      {workflowPage === "pipeline" ? <>
      <main className="pipeline-editor"><div className="pipeline-name-row"><label>Pipeline name<input value={config.name} onChange={(event) => setConfig({ ...config, name: event.target.value })} /></label><label>Description<input value={config.description} onChange={(event) => setConfig({ ...config, description: event.target.value })} placeholder="Optional" /></label></div>
        <section className="pipeline-start-input"><label>Starting official output<select value={isAsrPipeline ? "__audio__" : initialOutputName} disabled={isAsrPipeline} onChange={(event) => setConfig({ ...config, initial_output_name: event.target.value })}>
          {isAsrPipeline ? <option value="__audio__">Audio recording · transcription stage creates the text</option> : <>
            {recordingIds.length > 0 && !commonInitialOutputs.some((output) => output.name.toLocaleLowerCase() === initialOutputName.toLocaleLowerCase()) && <option value={initialOutputName}>{initialOutputName} · unavailable for all selected recordings</option>}
            {commonInitialOutputs.map((output) => <option key={output.id} value={output.name}>{output.name} · {output.kind}</option>)}
            {!recordingIds.length && <option value="Transcription">Transcription · select recordings to see available outputs</option>}
          </>}
        </select><small>{isAsrPipeline ? "The first stage uses the audio and publishes a new official transcription." : `Text stages require an official transcription. This run will start from “${initialOutputName}”.${recordingIds.length && !selectedInputsAvailable ? " One or more selected recordings are missing this output or an official transcription." : ""}`}</small></label></section>
        <section className="pipeline-input-summary" aria-label="Selected recordings">
          <details className="selected-recording-details"><summary><b>Recordings Selected · {recordingIds.length}</b></summary>
            <div className="selected-recordings-table-wrap"><table className="selected-recordings-table"><thead><tr><th>Recording</th><th>Recorded time</th><th>File length</th><th>Est. Cost</th></tr></thead><tbody>{recordingIds.map((id) => {
              const recording = selectedRecordings.find((item) => item.id === id);
              const estimate = perRecordingEstimates.find((item) => item.recordingId === id);
              return <tr key={id}><td title={recording?.original_name}>{recording?.original_name ?? "Recording"}</td><td>{formatRecordedTime(recording?.media_date)}</td><td>{formatDuration(recording?.duration_seconds ?? null)}</td><td>{formatEstimatedCost(estimate?.cost ?? null)}</td></tr>;
            })}</tbody></table></div></details>
        </section>
        <details className="pipeline-estimate-breakdown" aria-label="Cost breakdown by stage"><summary>Cost Breakdown · {formatEstimatedCost(totalEstimatedCost)}</summary><div className="pipeline-estimate-table-wrap"><table className="pipeline-estimate-table"><thead><tr><th>Stage</th><th>Input tokens</th><th>Input cost</th><th>Output tokens</th><th>Output cost</th><th>Total</th></tr></thead><tbody>{usageEstimates.map(({ step, inputTokens, outputTokens, audioSeconds, inputCost, outputCost, costKnown }) => <tr key={step.id}><td>{step.name || step.kind}</td><td>{step.kind === "transcription" ? formatDuration(audioSeconds) : transcriptsAvailable ? `~${inputTokens.toLocaleString()}` : "—"}</td><td>{step.kind === "transcription" ? "Local" : transcriptsAvailable && costKnown ? formatEstimatedCost(inputCost) : "—"}</td><td>{transcriptsAvailable ? `~${outputTokens.toLocaleString()}` : "—"}</td><td>{step.kind === "transcription" ? "Local" : transcriptsAvailable && costKnown ? formatEstimatedCost(outputCost) : "—"}</td><td>{step.kind === "transcription" ? "Local" : transcriptsAvailable && costKnown ? formatEstimatedCost(inputCost + outputCost) : "—"}</td></tr>)}</tbody></table></div>
          <p className="pipeline-estimate-note">Approximate only: token counts use about 4 characters per token. Cleanup and verification assume output at 90% of raw transcript size; summaries assume 500 words; titles assume 10 words. Costs use current OpenRouter catalog prices. {hasTranscriptionStage && "Transcript size is estimated from audio length at 150 spoken words per minute. "}{transcriptsAvailable < recordingIds.length ? `Estimates include ${transcriptsAvailable} of ${recordingIds.length} selected recordings with available transcript text or audio duration.` : "Actual tokenization and response length will vary."}</p>
        </details>
        <div className="stage-heading"><div><b>Ordered stages</b><span>Text stages can use the starting official output or an earlier stage output.</span></div><button className="quiet-button" onClick={() => setConfig({ ...config, steps: [...config.steps, { ...newStep(), name: "New stage", prompt: "" }] })}><Plus size={14} /> Add stage</button></div>
        <div className="stage-list">{config.steps.map((step, index) => <article className="stage-card" key={step.id}><div className="stage-card-head"><span className="stage-number">{index + 1}</span><input aria-label={`Stage ${index + 1} name`} value={step.kind === "transcription" ? "Transcription" : step.name} disabled={step.kind === "transcription"} onChange={(event) => updateStep(index, { name: event.target.value })} /><div className="stage-reorder"><button aria-label="Move stage up" disabled={!index || (index === 1 && config.steps[0].kind === "transcription")} onClick={() => moveStep(index, -1)}><ChevronUp size={15} /></button><button aria-label="Move stage down" disabled={index === config.steps.length - 1 || step.kind === "transcription"} onClick={() => moveStep(index, 1)}><ChevronDown size={15} /></button></div><button className="remove-stage" aria-label="Remove stage" disabled={config.steps.length === 1} onClick={() => removeStep(index)}><X size={15} /></button></div>
          {step.kind !== "transcription" && step.name.trim().toLocaleLowerCase() === "transcription" && <small className="stage-name-warning">“Transcription” is reserved for the local ASR output so text stages cannot replace the required transcript.</small>}
          <div className="stage-fields"><label>Stage type<select value={step.kind} onChange={(event) => changeStepKind(index, event.target.value)}><option value="transcription">Transcription</option><option value="cleanup">Cleanup</option><option value="verification">Verification</option><option value="summary">Summary / topics</option><option value="title">Title</option><option value="custom">Custom</option></select></label>{step.kind === "transcription" ? <><label>Input source<select defaultValue="audio" disabled><option value="audio">Audio recording</option></select></label><label>Local transcription model<select value={step.model} onChange={(event) => updateStep(index, { model: event.target.value })} disabled={!transcriptionModels.length}>{transcriptionModels.length ? transcriptionModels.map((model) => <option key={model.id} value={model.id}>{model.name} · {model.provider}</option>) : <option value={step.model}>{transcriptionModelsError ? "Model list unavailable" : "Loading local models…"}</option>}</select><small>{transcriptionModelsError || [transcriptionModels.find((model) => model.id === step.model)?.languages, transcriptionModels.find((model) => model.id === step.model)?.timing].filter(Boolean).join(" · ") || "Select the local model used to create the raw transcript."}</small></label></> : <><label>Input source<select value={step.input_ref} onChange={(event) => updateStep(index, { input_ref: event.target.value })}><option value="raw">Starting official output · {initialOutputName}</option>{config.steps.slice(0, index).map((prior) => <option key={prior.id} value={prior.id}>{prior.name} output</option>)}</select></label><ModelPicker value={step.model} models={models} error={modelsError} onChange={(model) => updateStep(index, { model })} /></>}</div>
          {step.kind !== "transcription" && <label className="prompt-field">Prompt<textarea value={step.prompt} onChange={(event) => updateStep(index, { prompt: event.target.value })} rows={3} placeholder="Describe the transformation for this stage" /></label>}</article>)}</div>
        <div className="workflow-actions"><span>{recordingIds.length ? `${recordingIds.length} recording${recordingIds.length === 1 ? "" : "s"} selected` : "Select recordings in the library to run this pipeline."}</span><div>{pipelineId && <button className="quiet-button" onClick={() => void duplicate()}><Copy size={14} /> Duplicate</button>}<button className="quiet-button" onClick={() => void save()} disabled={busy}><Save size={14} /> Save pipeline</button><button className="quiet-button simulate-button" title={hasTranscriptionStage ? "Simulation is available only for text-only pipelines" : "Simulate the first selected recording locally without contacting OpenRouter"} onClick={() => void simulate()} disabled={busy || hasTranscriptionStage || !recordingIds.length || !selectedInputsAvailable}><Play size={14} /> Simulate</button><button className="workflow-run" onClick={() => void run()} disabled={busy || !pipelineId || !recordingIds.length || !selectedInputsAvailable}><Play size={14} /> Run pipeline</button></div></div>
        {message && <div className="workflow-message">{message}</div>}
      </main>
      </> : <>
        <RunQueuePanel items={queueItems} currentRecordingId={currentRunRecordingId} selectedRecordingId={focusRecordingId} run={activeRun} message={message} onSelect={(id) => { setFlowRecordingId(id); setManualQueueSelection(true); }} onGoToPipeline={() => setWorkflowPage("pipeline")} />
        <div className="flow-panel-resizer" role="separator" aria-label="Resize execution flow panel" aria-orientation="vertical" aria-valuemin={280} aria-valuemax={760} aria-valuenow={flowPanelWidth} tabIndex={0} onPointerDown={(event) => { resizeStart.current = { x: event.clientX, width: flowPanelWidth }; event.currentTarget.setPointerCapture(event.pointerId); }} onPointerMove={(event) => { if (!resizeStart.current) return; const maximum = Math.min(760, window.innerWidth - 420 - 40); setFlowPanelWidth(Math.max(280, Math.min(maximum, resizeStart.current.width + resizeStart.current.x - event.clientX))); }} onPointerUp={(event) => { resizeStart.current = null; event.currentTarget.releasePointerCapture(event.pointerId); }} onKeyDown={(event) => { if (event.key === "ArrowLeft") setFlowPanelWidth((width) => Math.min(760, width + 20)); if (event.key === "ArrowRight") setFlowPanelWidth((width) => Math.max(280, width - 20)); }} />
        <PipelineFlow config={activeRun?.pipeline_snapshot ?? config} run={activeRun} previewTranscript={(officialOutputsByRecording[focusRecordingId] ?? []).find((output) => output.name.toLocaleLowerCase() === initialOutputName.toLocaleLowerCase()) ?? null} previewRecordingName={queueRecordings.find((recording) => recording.id === focusRecordingId)?.original_name ?? "Select a recording"} recordingId={flowRecordingId || focusRecordingId} onRetry={() => void retry()} />
      </>}
    </div>
  </section></div>;
}

/** Show batch progress and let the user focus the execution flow on any recording. */
function RunQueuePanel({ items, currentRecordingId, selectedRecordingId, run, message, onSelect, onGoToPipeline }: {
  items: RecordingQueueItem[];
  currentRecordingId: string;
  selectedRecordingId: string;
  run: PipelineRun | null;
  message: string;
  onSelect: (id: string) => void;
  onGoToPipeline: () => void;
}) {
  const activeIndex = items.findIndex((item) => item.id === currentRecordingId);
  const completedCount = items.filter((item) => item.status === "completed").length;
  const failedCount = items.filter((item) => item.status === "failed").length;
  const remainingCount = activeIndex < 0 ? items.length : Math.max(0, items.length - activeIndex - 1);
  const progress = !run
    ? `${items.length} recording${items.length === 1 ? "" : "s"} selected`
    : run.status === "succeeded"
      ? `${completedCount} of ${items.length} recordings complete`
      : run.status === "failed"
        ? `${failedCount} failed · ${items.length - completedCount} unfinished`
        : `File ${Math.max(1, activeIndex + 1)} of ${items.length} · ${remainingCount} remaining`;

  function statusLabel(status: RecordingQueueItem["status"]): string {
    if (status === "processing") return "Processing";
    if (status === "completed") return "Complete";
    if (status === "failed") return "Failed";
    if (status === "queued") return "Queued";
    return "Ready";
  }

  return <aside className="recording-queue" aria-label="Recording run queue">
    <header className="recording-queue-header"><div><span>RUN QUEUE</span><h3>{progress}</h3></div>{run && <span className={`run-state ${run.pipeline_id === "simulation" ? "state-preview" : `state-${run.status}`}`}>{run.pipeline_id === "simulation" ? "simulation" : run.status}</span>}</header>
    {run && <div className="recording-queue-subtitle">{run.pipeline_name}</div>}
    {message && <div className="workflow-message" style={{ margin: "10px 12px 0" }}>{message}</div>}
    <div className="recording-queue-list">
      {items.length ? items.map((item, index) => <button key={item.id} className={`recording-queue-item queue-${item.status} ${item.id === currentRecordingId ? "queue-current" : ""} ${item.id === selectedRecordingId ? "queue-selected" : ""}`} aria-current={item.id === currentRecordingId ? "step" : undefined} onClick={() => onSelect(item.id)}>
        <span className={`queue-status-mark queue-mark-${item.status}`} aria-hidden="true">{item.status === "processing" ? <span /> : item.status === "completed" ? "✓" : item.status === "failed" ? "!" : index + 1}</span>
        <span className="queue-item-copy"><b title={item.original_name}>{item.original_name}</b><small>{formatDuration(item.duration_seconds)} · {statusLabel(item.status)}</small></span>
        {item.id === currentRecordingId && <span className="queue-current-label">CURRENT</span>}
      </button>) : <div className="recording-queue-empty"><p>No recordings are selected for a run.</p><button className="quiet-button" onClick={onGoToPipeline}>Go to Pipeline</button></div>}
    </div>
    {items.length > 0 && !run && <p className="recording-queue-hint">Configure and save a pipeline on the Pipeline tab to start processing.</p>}
  </aside>;
}

/** Show the frozen official input followed by live, ordered stage states and outputs. */
function PipelineFlow({ config, run, previewTranscript, previewRecordingName, recordingId, onRetry }: {
  config: PipelineConfig;
  run: PipelineRun | null;
  previewTranscript: OfficialOutput | null;
  previewRecordingName: string;
  recordingId: string;
  onRetry: () => void;
}) {
  const inputs = run?.inputs ?? [];
  const selectedInput = inputs.find((item) => item.recording_id === recordingId) ?? inputs[0];
  const selectedRecordingId = selectedInput?.recording_id ?? (recordingId || run?.stages[0]?.recording_id || "");
  const stages = run && selectedInput
    ? run.stages.filter((stage) => stage.recording_id === selectedInput.recording_id).sort((a, b) => a.step_index - b.step_index)
    : run && selectedRecordingId
      ? run.stages.filter((stage) => stage.recording_id === selectedRecordingId).sort((a, b) => a.step_index - b.step_index)
      : [];
  const preview = !run;
  const startsWithTranscription = config.steps[0]?.kind === "transcription";
  const hasRunningStage = stages.some((stage) => stage.status === "running");
  const [clock, setClock] = useState(Date.now());
  useEffect(() => {
    if (!hasRunningStage) return;
    const timer = window.setInterval(() => setClock(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, [hasRunningStage, run?.id]);

  /** Format a stage duration as elapsed seconds or minutes and seconds. */
  function elapsedTime(stage: PipelineRun["stages"][number]): string | null {
    if (!stage.started_at) return null;
    const end = stage.finished_at ? Date.parse(stage.finished_at) : clock;
    const total = Math.max(0, Math.floor((end - Date.parse(stage.started_at)) / 1000));
    return total >= 60 ? `${Math.floor(total / 60)}m ${total % 60}s` : `${total}s`;
  }

  return <aside className="pipeline-flow-panel" aria-label="Pipeline execution flow">
    <header className="flow-panel-header"><div><span>EXECUTION FLOW</span><h3>{run ? selectedInput?.original_name ?? previewRecordingName : previewRecordingName}</h3></div>{run && <span className={`run-state ${run.pipeline_id === "simulation" ? "state-preview" : `state-${run.status}`}`}>{run.pipeline_id === "simulation" ? "simulation" : run.status}</span>}</header>
    {run && <div className="flow-run-meta">{inputs.length} recording{inputs.length === 1 ? "" : "s"} · {run.started_at ? new Date(run.started_at).toLocaleTimeString() : "Queued"}</div>}
    <div className="flow-scroll">
      <article className="flow-node flow-input-node"><div className="flow-node-heading"><span className="flow-node-icon">{startsWithTranscription ? "A" : "T"}</span><div><b>{startsWithTranscription ? "Audio recording" : run?.inputs?.find((item) => item.recording_id === selectedRecordingId)?.source_output_name ?? previewTranscript?.name ?? config.initial_output_name ?? "Official output"}</b><small>{run ? startsWithTranscription ? selectedInput?.original_name ?? "Recording" : `Official input · ${selectedInput?.original_name ?? "Recording"}` : startsWithTranscription ? "Source audio file" : previewTranscript ? `Official text · ${previewTranscript.kind}` : "Official output selected at the top"}</small></div><span className={`flow-node-state ${preview ? "state-preview" : "state-succeeded"}`}>{preview ? "INPUT" : "READY"}</span></div>
        <pre>{startsWithTranscription ? run ? stages.find((stage) => stage.step_index === 0)?.input_text ?? `Audio will be transcribed locally from ${selectedInput?.original_name ?? "the selected recording"}.` : `Audio will be transcribed locally using ${config.steps[0].model}.` : run ? selectedInput?.raw_content ?? "Official input unavailable for this run." : previewTranscript?.content ?? "Select a recording with the chosen official output to preview its input."}</pre>
      </article>
      {config.steps.map((step, index) => {
        const stage = stages.find((item) => item.step_id === step.id) ?? stages[index];
        const state = preview ? "preview" : stage?.status ?? "queued";
        const requestText = stage?.input_text == null
          ? null
          : stage.provider === "simulation" || stage.provider === "local_asr"
            ? stage.input_text
            : `${stage.prompt}\n\nInput transcript:\n${stage.input_text}`;
        return <div className="flow-step-wrap" key={step.id}>
          <div className={`flow-connector ${state === "running" ? "connector-running" : ""}`} aria-hidden="true"><span /></div>
          <article className={`flow-node flow-stage-node state-${state}`}>
            <div className="flow-node-heading"><span className="flow-node-icon flow-stage-icon">{state === "running" ? <span className="flow-spinner" /> : index + 1}</span><div><b>{stage?.step_name ?? step.name}</b><small>{step.kind === "transcription" ? `Local ASR · ${stage?.model ?? step.model}` : (stage?.model ?? step.model) || "Choose an OpenRouter model"}</small>{stage && elapsedTime(stage) && <small className="flow-step-time">Elapsed {elapsedTime(stage)}</small>}</div><span className={`flow-node-state state-${state}`}>{state === "preview" ? "WAITING" : state.toUpperCase()}</span></div>
            {preview && step.kind === "cleanup" && <div className="flow-prompt-preview"><span>CLEANUP PROMPT</span><p>{step.prompt || "Add instructions for how this stage should clean the transcript."}</p></div>}
            {stage?.error && <p className="flow-stage-error">{stage.error}</p>}
            <div className="flow-stage-io">
              <section className="flow-io-column flow-input-column"><ExpandableText label={stage?.provider === "simulation" ? "SIMULATED INPUT" : stage?.provider === "local_asr" ? "LOCAL AUDIO INPUT" : "API INPUT"} text={requestText} emptyMessage={preview ? "The stage input will appear here when the pipeline runs." : "Waiting for this stage to start."} /></section>
              <section className={`flow-io-column flow-output-column ${stage?.output_text ? "flow-output-ready" : "flow-output-pending"}`}><ExpandableText label="OUTPUT" text={stage?.output_text ?? null} emptyMessage={preview ? "The stage output will appear here after the pipeline runs." : state === "failed" ? "This stage did not return an output." : "Waiting for this stage to finish."} /></section>
            </div>
          </article>
        </div>;
      })}
      {config.steps.length === 0 && <div className="flow-empty">Add a stage to build this pipeline.</div>}
    </div>
    {run?.status === "failed" && <button className="quiet-button flow-retry" onClick={onRetry}>Retry failed stages</button>}
  </aside>;
}

/** Keep long stage text compact while allowing the full saved request or response to be inspected. */
function ExpandableText({ label, text, emptyMessage }: { label: string; text: string | null; emptyMessage: string }) {
  const [expanded, setExpanded] = useState(false);
  const words = text?.trim() ? text.trim().split(/\s+/) : [];
  const truncated = words.length > 20;
  const displayedText = expanded || !truncated ? text : `${words.slice(0, 20).join(" ")}…`;

  return <>
    <div className="flow-io-heading"><span>{label}</span>{truncated && <button type="button" onClick={() => setExpanded((value) => !value)}>{expanded ? "Show less" : "Expand"}</button>}</div>
    {displayedText !== null ? <pre className={expanded ? "flow-io-expanded" : ""}>{displayedText}</pre> : <p>{emptyMessage}</p>}
  </>;
}

/** Search model IDs, names, and publishers while showing each model's token costs. */
function ModelPicker({ value, models, error, onChange }: { value: string; models: OpenRouterModel[]; error: string; onChange: (value: string) => void }) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const matches = models.filter((model) => `${model.id} ${model.name} ${model.publisher}`.toLocaleLowerCase().includes(value.trim().toLocaleLowerCase())).sort((a, b) => b.created - a.created).slice(0, 40);

  /** Show compact per-million prices, retaining unknown prices as unavailable. */
  function cost(input: number | null, output: number | null): string {
    const format = (amount: number | null) => amount === null ? "—" : amount === 0 ? "Free" : `$${amount.toLocaleString(undefined, { maximumFractionDigits: 4 })}`;
    return `${format(input)} in · ${format(output)} out / 1M tokens`;
  }

  /** Apply a selected catalog item while keeping free-form model IDs supported. */
  function choose(model: OpenRouterModel): void { onChange(model.id); setOpen(false); }

  return <label className="model-field">OpenRouter model
    <div className="model-picker">
      <input role="combobox" aria-autocomplete="list" aria-expanded={open} aria-controls="openrouter-model-options" value={value} onFocus={() => { setOpen(true); setActiveIndex(0); }} onChange={(event) => { onChange(event.target.value); setOpen(true); setActiveIndex(0); }} onBlur={() => window.setTimeout(() => setOpen(false), 120)} onKeyDown={(event) => {
        if (event.key === "ArrowDown" && matches.length) { event.preventDefault(); setOpen(true); setActiveIndex((index) => (index + 1) % matches.length); }
        if (event.key === "ArrowUp" && matches.length) { event.preventDefault(); setActiveIndex((index) => (index - 1 + matches.length) % matches.length); }
        if (event.key === "Enter" && open && matches[activeIndex]) { event.preventDefault(); choose(matches[activeIndex]); }
        if (event.key === "Escape") setOpen(false);
      }} placeholder="Search by model, publisher, or ID" />
      {open && <div className="model-suggestions" id="openrouter-model-options" role="listbox">
        {models.length === 0 ? <div className="model-empty">{error ? `Model list unavailable: ${error}` : "Loading OpenRouter models…"}</div> : matches.length === 0 ? <div className="model-empty">No matching models. You can keep the typed model ID.</div> : matches.map((model, index) => <button type="button" role="option" aria-selected={index === activeIndex} className={`model-option ${index === activeIndex ? "model-option-active" : ""}`} key={model.id} onMouseDown={(event) => event.preventDefault()} onMouseEnter={() => setActiveIndex(index)} onClick={() => choose(model)}><span className="model-option-main"><b>{model.name}</b><small>{model.publisher} · {model.id}</small></span><span className="model-option-cost">{cost(model.input_cost_per_million, model.output_cost_per_million)}</span></button>)}
      </div>}
    </div>
  </label>;
}
