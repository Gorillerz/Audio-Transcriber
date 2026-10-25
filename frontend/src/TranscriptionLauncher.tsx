/** Provider selection and progress dialog for local word-timed Whisper runs. */
import { useEffect, useMemo, useState } from "react";
import { AlertCircle, AudioLines, CheckCircle2, Clock3, Cpu, LoaderCircle, X } from "lucide-react";
import { fetchLatestTranscription, fetchTranscriptionProviders, fetchTranscriptionRun, startTranscription } from "./api";
import type { Recording, TranscriptionProvider, TranscriptionRun } from "./types";

/** Format estimates as readable minutes and seconds without implying false precision. */
function formatTime(seconds: number | null): string {
  if (seconds === null) return "Unavailable";
  const whole = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(whole / 60);
  const remainder = whole % 60;
  return minutes ? `${minutes}m ${remainder}s` : `${remainder}s`;
}

/** Let the user select the available ASR option and track its run without hiding the estimate. */
export default function TranscriptionLauncher({ recording, onClose, onComplete }: {
  recording: Recording;
  onClose: () => void;
  onComplete: () => void;
}) {
  const [providers, setProviders] = useState<TranscriptionProvider[]>([]);
  const [providerId, setProviderId] = useState("wsl-whisper");
  const [run, setRun] = useState<TranscriptionRun | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [loading, setLoading] = useState(true);
  const [launching, setLaunching] = useState(false);
  const [error, setError] = useState("");
  const selectedProvider = useMemo(() => providers.find((provider) => provider.id === providerId) ?? null, [providers, providerId]);

  useEffect(() => {
    let active = true;
    async function load(): Promise<void> {
      /** Load provider readiness and restore an in-flight or completed run for this recording. */
      setLoading(true);
      setError("");
      try {
        const [available, latest] = await Promise.all([
          fetchTranscriptionProviders(recording.id), fetchLatestTranscription(recording.id),
        ]);
        if (!active) return;
        setProviders(available);
        setRun(latest);
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Could not check transcription options.");
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => { active = false; };
  }, [recording.id]);

  useEffect(() => {
    if (!run || run.status !== "running") return;
    let active = true;
    const poll = async () => {
      /** Refresh the persistent run state; the UI timer itself remains local and lightweight. */
      try {
        const updated = await fetchTranscriptionRun(run.id);
        if (active) setRun(updated);
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Could not refresh transcription progress.");
      }
    };
    void poll();
    const interval = window.setInterval(() => { setElapsed((seconds) => seconds + 1); void poll(); }, 1000);
    return () => { active = false; window.clearInterval(interval); };
  }, [run?.id, run?.status]);

  useEffect(() => {
    if (run?.status !== "succeeded") return;
    window.dispatchEvent(new CustomEvent("journal:official-outputs-updated", { detail: { recordingId: recording.id } }));
    onComplete();
  }, [run?.status]);

  async function launch(): Promise<void> {
    /** Start only the selected provider and switch the dialog into its monitored run state. */
    if (!selectedProvider) return;
    setLaunching(true);
    setError("");
    setElapsed(0);
    try {
      const started = await startTranscription(recording.id, selectedProvider.id);
      setRun(started);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start transcription.");
    } finally {
      setLaunching(false);
    }
  }

  const secondsElapsed = Math.max(elapsed, run?.elapsed_seconds ?? 0);
  const remaining = selectedProvider?.estimated_seconds == null ? null : selectedProvider.estimated_seconds - secondsElapsed;
  const isRunning = run?.status === "running";
  const canLaunch = Boolean(selectedProvider?.available && recording.duration_seconds !== null && !isRunning && !launching && !loading);

  return <div className="confirm-overlay transcription-overlay" role="presentation">
    <section className="confirm-dialog transcription-dialog" role="dialog" aria-modal="true" aria-labelledby="transcription-title">
      <div className="transcription-heading"><div><span className="transcription-eyebrow">LOCAL SPEECH TO TEXT</span><h2 id="transcription-title">Transcribe Recording</h2><p title={recording.original_name}>{recording.original_name}</p></div><button className="icon-button" aria-label="Close transcription dialog" onClick={onClose} disabled={isRunning}><X size={17} /></button></div>
      {loading ? <div className="transcription-loading"><LoaderCircle className="spin" size={18} /> Checking local transcription options…</div> : <>
        <div className="transcription-options-label">AVAILABLE MODEL</div>
        {providers.map((provider) => <button key={provider.id} className={`transcription-provider ${providerId === provider.id ? "provider-selected" : ""} ${!provider.available ? "provider-unavailable" : ""}`} onClick={() => setProviderId(provider.id)}>
          <span className="provider-mark"><AudioLines size={18} /></span><span className="provider-copy"><b>{provider.name}</b><small>{provider.provider} · {provider.model}</small><small>{provider.languages} · {provider.timing}</small></span><span className={`provider-radio ${providerId === provider.id ? "radio-selected" : ""}`} />
        </button>)}
        {selectedProvider && <div className="transcription-device"><Cpu size={16} /><span><b>{selectedProvider.gpu_name ?? "Local GPU not detected"}</b><small>{selectedProvider.available ? recording.duration_seconds === null ? "Audio duration is unavailable; transcription cannot be estimated yet." : "Detected through WSL · audio stays on this computer" : selectedProvider.reason}</small></span></div>}
        <div className="transcription-estimate"><div><span>ESTIMATED TIME</span><b>{formatTime(selectedProvider?.estimated_seconds ?? null)}</b></div><div><span>DEVICE</span><b>Local GPU</b></div><small>{selectedProvider?.estimate_note}</small></div>
        {isRunning && <div className="transcription-running" aria-live="polite"><div className="transcription-run-title"><span className="transcription-spinner" /><b>Transcription is running</b><span className="running-tag">IN PROGRESS</span></div><div className="transcription-progress-track"><span /></div><div className="transcription-timers"><span><Clock3 size={13} /> Elapsed <b>{formatTime(secondsElapsed)}</b></span><span>Estimated remaining <b>{remaining === null ? "—" : remaining > 0 ? formatTime(remaining) : "Longer than estimated"}</b></span></div><small>Progress is estimated from the benchmark; the model does not report an exact percentage.</small></div>}
        {run?.status === "succeeded" && run.result && <div className="transcription-result"><div><CheckCircle2 size={16} /><b>Transcription complete</b><span>{run.result.words.length.toLocaleString()} timed words</span></div><p>{run.result.text}</p></div>}
        {run?.status === "failed" && <div className="transcription-error"><AlertCircle size={15} /><span>{run.error || "The transcription failed."}</span></div>}
        {error && <div className="transcription-error"><AlertCircle size={15} /><span>{error}</span></div>}
        <div className="transcription-actions"><button className="quiet-button" onClick={onClose} disabled={isRunning}>Close</button><button className="primary-button" onClick={() => void launch()} disabled={!canLaunch}><AudioLines size={15} />{launching ? "Starting…" : run?.status === "failed" ? "Retry transcription" : run?.status === "succeeded" ? "Transcribe again" : "Launch transcription"}</button></div>
      </>}
    </section>
  </div>;
}
