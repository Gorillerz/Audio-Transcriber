/** Pipeline editor and run monitor for transcript-only OpenRouter workflows. */
import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Copy, Plus, Play, Save, X } from "lucide-react";
import { duplicatePipeline, fetchPipeline, fetchPipelineRun, fetchPipelineRuns, fetchPipelines, retryPipelineRun, savePipeline, startPipelineRun } from "./api";
import type { PipelineConfig, PipelineRun, PipelineStep, SavedPipeline } from "./types";

const newStep = (): PipelineStep => ({ id: crypto.randomUUID(), name: "Cleanup", kind: "cleanup", model: "", prompt: "Clean up the transcript while preserving its meaning and language.", input_ref: "raw", output_format: "text" });

/** Edit reusable stage chains, launch selected recordings, and review saved run outputs. */
export default function PipelineManager({ open, recordingIds, onClose }: { open: boolean; recordingIds: string[]; onClose: () => void }) {
  const [pipelines, setPipelines] = useState<SavedPipeline[]>([]);
  const [pipelineId, setPipelineId] = useState("");
  const [config, setConfig] = useState<PipelineConfig>({ name: "New pipeline", description: "", steps: [newStep()] });
  const [runs, setRuns] = useState<Array<{ id: string; pipeline_name: string; status: string; created_at: string; total_stages: number; succeeded_stages: number; failed_stages: number }>>([]);
  const [activeRun, setActiveRun] = useState<PipelineRun | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  /** Load reusable definitions and recent runs whenever the modal opens. */
  useEffect(() => { if (open) void refresh().then((saved) => { if (!pipelineId && saved.length) void loadPipeline(saved[0].id); }); }, [open]);

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
      setPipelineId(id); setConfig(item.config ?? { name: item.name, description: item.description, steps: [] }); setMessage("");
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

  /** Start a single or batch run using only the selected recordings' latest raw input. */
  async function run(): Promise<void> {
    if (!pipelineId || !recordingIds.length) return;
    setBusy(true);
    try {
      const created = await startPipelineRun(pipelineId, recordingIds);
      setActiveRun(created); setMessage("Pipeline queued."); await refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not start pipeline."); }
    finally { setBusy(false); }
  }

  /** Poll the persisted run record while its stages are queued or running. */
  useEffect(() => {
    if (!activeRun || !["queued", "running"].includes(activeRun.status)) return;
    const timer = window.setInterval(() => { void fetchPipelineRun(activeRun.id).then(setActiveRun).catch(() => undefined); }, 1200);
    return () => window.clearInterval(timer);
  }, [activeRun?.id, activeRun?.status]);

  /** Retry only failed stages while completed stage results remain stored. */
  async function retry(): Promise<void> {
    if (!activeRun) return;
    try { setActiveRun(await retryPipelineRun(activeRun.id)); setMessage("Failed stages queued for retry."); await refresh(); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Could not retry run."); }
  }

  /** Update one step without changing the rest of the ordered pipeline. */
  function updateStep(index: number, patch: Partial<PipelineStep>): void {
    setConfig((current) => ({ ...current, steps: current.steps.map((step, item) => item === index ? { ...step, ...patch } : step) }));
  }

  /** Move a step and keep its output binding IDs stable for downstream steps. */
  function moveStep(index: number, offset: number): void {
    const target = index + offset;
    if (target < 0 || target >= config.steps.length) return;
    setConfig((current) => { const steps = [...current.steps]; [steps[index], steps[target]] = [steps[target], steps[index]]; return { ...current, steps }; });
  }

  const modelHint = useMemo(() => "Use an OpenRouter model ID, for example provider/model-name.", []);
  if (!open) return null;
  return <div className="workflow-overlay"><section className="workflow-window" role="dialog" aria-modal="true" aria-labelledby="workflow-title">
    <header className="workflow-header"><div><span className="workflow-eyebrow">TEXT PROCESSING</span><h2 id="workflow-title">Pipeline Workflows</h2></div><button className="icon-button" aria-label="Close workflows" onClick={onClose}><X size={18} /></button></header>
    <div className="workflow-body"><aside className="pipeline-list"><div className="pipeline-list-title">SAVED PIPELINES</div><button className={`pipeline-option ${!pipelineId ? "selected" : ""}`} onClick={() => { setPipelineId(""); setConfig({ name: "New pipeline", description: "", steps: [newStep()] }); setActiveRun(null); }}> <Plus size={15} /> New pipeline</button>{pipelines.map((pipeline) => <button key={pipeline.id} className={`pipeline-option ${pipeline.id === pipelineId ? "selected" : ""}`} onClick={() => { void loadPipeline(pipeline.id); setActiveRun(null); }}><span>{pipeline.name}</span><small>v{pipeline.version}</small></button>)}<div className="pipeline-list-title recent-title">RECENT RUNS</div>{runs.slice(0, 8).map((runItem) => <button key={runItem.id} className={`run-option ${activeRun?.id === runItem.id ? "selected" : ""}`} onClick={() => void fetchPipelineRun(runItem.id).then(setActiveRun)}><span>{runItem.pipeline_name}</span><small>{runItem.status} · {runItem.succeeded_stages}/{runItem.total_stages}</small></button>)}</aside>
      <main className="pipeline-editor"><div className="pipeline-name-row"><label>Pipeline name<input value={config.name} onChange={(event) => setConfig({ ...config, name: event.target.value })} /></label><label>Description<input value={config.description} onChange={(event) => setConfig({ ...config, description: event.target.value })} placeholder="Optional" /></label></div>
        <div className="stage-heading"><div><b>Ordered stages</b><span>Each stage can use the raw transcript or an earlier stage output.</span></div><button className="quiet-button" onClick={() => setConfig({ ...config, steps: [...config.steps, { ...newStep(), name: "New stage", prompt: "" }] })}><Plus size={14} /> Add stage</button></div>
        <div className="stage-list">{config.steps.map((step, index) => <article className="stage-card" key={step.id}><div className="stage-card-head"><span className="stage-number">{index + 1}</span><input aria-label={`Stage ${index + 1} name`} value={step.name} onChange={(event) => updateStep(index, { name: event.target.value })} /><div className="stage-reorder"><button aria-label="Move stage up" disabled={!index} onClick={() => moveStep(index, -1)}><ChevronUp size={15} /></button><button aria-label="Move stage down" disabled={index === config.steps.length - 1} onClick={() => moveStep(index, 1)}><ChevronDown size={15} /></button></div><button className="remove-stage" aria-label="Remove stage" disabled={config.steps.length === 1} onClick={() => setConfig({ ...config, steps: config.steps.filter((_, item) => item !== index) })}><X size={15} /></button></div>
          <div className="stage-fields"><label>Stage type<select value={step.kind} onChange={(event) => updateStep(index, { kind: event.target.value })}><option value="cleanup">Cleanup</option><option value="verification">Verification</option><option value="summary">Summary / topics</option><option value="title">Title</option><option value="custom">Custom</option></select></label><label>Input source<select value={step.input_ref} onChange={(event) => updateStep(index, { input_ref: event.target.value })}><option value="raw">Raw transcript</option>{config.steps.slice(0, index).map((prior) => <option key={prior.id} value={prior.id}>{prior.name} output</option>)}</select></label><label>Output format<select value={step.output_format} onChange={(event) => updateStep(index, { output_format: event.target.value as "text" | "json" })}><option value="text">Text</option><option value="json">JSON</option></select></label></div>
          <label className="model-field">OpenRouter model<input value={step.model} onChange={(event) => updateStep(index, { model: event.target.value })} placeholder="provider/model-name" title={modelHint} /></label><label className="prompt-field">Prompt<textarea value={step.prompt} onChange={(event) => updateStep(index, { prompt: event.target.value })} rows={3} placeholder="Describe the transformation for this stage" /></label></article>)}</div>
        <div className="workflow-actions"><span>{recordingIds.length ? `${recordingIds.length} recording${recordingIds.length === 1 ? "" : "s"} selected` : "Select recordings in the library to run this pipeline."}</span><div>{pipelineId && <button className="quiet-button" onClick={() => void duplicate()}><Copy size={14} /> Duplicate</button>}<button className="quiet-button" onClick={() => void save()} disabled={busy}><Save size={14} /> Save pipeline</button><button className="workflow-run" onClick={() => void run()} disabled={busy || !pipelineId || !recordingIds.length}><Play size={14} /> Run pipeline</button></div></div>
        {message && <div className="workflow-message">{message}</div>}
        {activeRun && <section className="run-results"><header><div><b>{activeRun.pipeline_name}</b><span className={`run-state state-${activeRun.status}`}>{activeRun.status}</span></div>{activeRun.status === "failed" && <button className="quiet-button" onClick={() => void retry()}>Retry failed stages</button>}</header>{activeRun.pipeline_snapshot && <p className="run-provenance">Pipeline version {activeRun.pipeline_snapshot.pipeline_version} · started {activeRun.started_at ? new Date(activeRun.started_at).toLocaleString() : "waiting"}</p>}<div className="run-stage-list">{activeRun.stages.map((stage) => <article key={stage.id}><div className="run-stage-title"><b>{stage.original_name} · {stage.step_name}</b><span className={`run-state state-${stage.status}`}>{stage.status}</span></div><small>{stage.provider} / {stage.model} · input: {stage.input_ref === "raw" ? "raw transcript" : "prior stage output"}</small>{stage.error && <p className="stage-error">{stage.error}</p>}{stage.output_text && <pre>{stage.output_text}</pre>}</article>)}</div></section>}
      </main>
    </div>
  </section></div>;
}
