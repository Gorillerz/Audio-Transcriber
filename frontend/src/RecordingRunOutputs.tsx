/** Manage official recording outputs and their recoverable previous-version archive. */
import { useCallback, useEffect, useRef, useState } from "react";
import { Archive, ArrowDown, ArrowUp, ChevronDown, ChevronUp, LoaderCircle, RefreshCw, RotateCcw } from "lucide-react";
import { archiveOfficialOutput, fetchOfficialOutputs, fetchOutputHistory, moveOfficialOutput, renameOfficialOutput, restoreHistoricalOutput } from "./api";
import { alignmentMatchesTranscript, areAllBlocksCollapsed, confidenceColor, countWords } from "./catalog";
import type { HistoricalOutput, OfficialOutput } from "./types";

const confidenceLegend = [
  { label: "25%", color: "#ef4444" },
  { label: "50%", color: "#f97316" },
  { label: "75%", color: "#a3e635" },
  { label: "100%", color: "#22c55e" },
];

/** Render aligned transcript words with hover scores and a local color visibility toggle. */
function TranscriptContent({
  output,
  recordingId,
  currentTime,
  colorsEnabled,
  onToggleColors,
}: {
  output: OfficialOutput | HistoricalOutput;
  recordingId: string;
  currentTime: number;
  colorsEnabled: boolean;
  onToggleColors: (enabled: boolean) => void;
}) {
  const words = output.word_alignment?.words ?? [];
  const hasScores = words.some((word) => confidenceColor(word.probability) !== null);
  if (!alignmentMatchesTranscript(output.content, words)) return <pre>{output.content}</pre>;

  return <div className="official-transcript-box">
    {hasScores && <div className="official-transcript-toolbar">
      <div className="confidence-legend" aria-label="Whisper word probability color guide">
        <span>Probability</span>{confidenceLegend.map((stop) => <span className="confidence-legend-stop" key={stop.label}>
          <i style={{ backgroundColor: stop.color }} />{stop.label}
        </span>)}
      </div>
      <button type="button" className="confidence-color-toggle" aria-pressed={colorsEnabled}
        onClick={() => onToggleColors(!colorsEnabled)}>{colorsEnabled ? "Hide colors" : "Show colors"}</button>
    </div>}
    <div className="official-transcript-text">
      {words.map((word, index) => {
        const probability = typeof word.probability === "number" && Number.isFinite(word.probability)
          ? Math.max(0, Math.min(1, word.probability)) : null;
        const color = colorsEnabled ? confidenceColor(probability) : null;
        const label = probability === null ? "Probability unavailable" : `Probability: ${Math.round(probability * 100)}%`;
        const active = currentTime >= word.start && currentTime < word.end;
        return <span key={`${word.start}-${index}`} className={`confidence-word transcript-audio-word${active ? " active-audio-word" : ""}`} title={label}
          role="button" tabIndex={0}
          aria-label={`${word.text.trim() || "Punctuation"}. ${label}`}
          style={color ? { backgroundColor: color } : undefined}
          onClick={() => window.dispatchEvent(new CustomEvent("journal:audio-seek", { detail: { recordingId, time: word.start, play: true } }))}
          onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); window.dispatchEvent(new CustomEvent("journal:audio-seek", { detail: { recordingId, time: word.start, play: true } })); } }}>{word.text}</span>;
      })}
    </div>
  </div>;
}

/** Show one current named output and a collapsed history of replaced or removed values. */
export default function RecordingRunOutputs({ recordingId }: { recordingId: string }) {
  const [outputs, setOutputs] = useState<OfficialOutput[]>([]);
  const [history, setHistory] = useState<HistoricalOutput[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [restoreId, setRestoreId] = useState("");
  const [restoreName, setRestoreName] = useState("");
  const [renamingId, setRenamingId] = useState("");
  const [draftName, setDraftName] = useState("");
  const [renameError, setRenameError] = useState("");
  const [confidenceColorsEnabled, setConfidenceColorsEnabled] = useState(true);
  const [audioTime, setAudioTime] = useState(0);
  const [collapsedBlocks, setCollapsedBlocks] = useState<Set<string>>(() => new Set());
  const renameRequest = useRef(false);
  const skipRenameBlur = useRef(false);

  /** Reload the official list and archive together so every action is reflected consistently. */
  const loadOutputs = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [current, previous] = await Promise.all([fetchOfficialOutputs(recordingId), fetchOutputHistory(recordingId)]);
      setOutputs(current);
      setHistory(previous);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load recording outputs.");
    } finally {
      setLoading(false);
    }
  }, [recordingId]);

  useEffect(() => {
    setOutputs([]);
    setHistory([]);
    setRestoreId("");
    setCollapsedBlocks(new Set());
    void loadOutputs();
  }, [loadOutputs]);

  useEffect(() => {
    /** Refresh after an ASR or pipeline run publishes new official output for this recording. */
    const refreshUpdatedRecording = (event: Event) => {
      const detail = (event as CustomEvent<{ recordingId: string }>).detail;
      if (detail?.recordingId === recordingId) void loadOutputs();
    };
    window.addEventListener("journal:official-outputs-updated", refreshUpdatedRecording);
    return () => window.removeEventListener("journal:official-outputs-updated", refreshUpdatedRecording);
  }, [loadOutputs, recordingId]);

  useEffect(() => {
    /** Follow playback time so aligned words can highlight and seek back into the audio. */
    const updateAudioTime = (event: Event) => {
      const detail = (event as CustomEvent<{ recordingId: string; time: number }>).detail;
      if (detail?.recordingId === recordingId) setAudioTime(detail.time);
    };
    window.addEventListener("journal:audio-time", updateAudioTime);
    setAudioTime(0);
    return () => window.removeEventListener("journal:audio-time", updateAudioTime);
  }, [recordingId]);

  /** Archive an output instead of deleting its content or execution provenance. */
  async function archive(output: OfficialOutput): Promise<void> {
    setBusyId(output.id);
    try { await archiveOfficialOutput(recordingId, output.id); await loadOutputs(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not move the output to previous versions."); }
    finally { setBusyId(""); }
  }

  /** Restore an archived value, asking for a distinct name when its former name is occupied. */
  async function restore(item: HistoricalOutput, name?: string): Promise<void> {
    if (!name && outputs.some((output) => output.name.localeCompare(item.name, undefined, { sensitivity: "accent" }) === 0)) {
      setRestoreId(item.id);
      setRestoreName(`${item.name} restored`);
      return;
    }
    setBusyId(item.id);
    setError("");
    try {
      await restoreHistoricalOutput(recordingId, item.id, name);
      setRestoreId("");
      await loadOutputs();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "Could not restore this output.";
      if (message.includes("Choose a different name")) {
        setRestoreId(item.id);
        setRestoreName(`${item.name} restored`);
      } else setError(message);
    } finally { setBusyId(""); }
  }

  /** Persist a one-place move and adopt the canonical order returned by the backend. */
  async function reorder(output: OfficialOutput, direction: "up" | "down"): Promise<void> {
    setBusyId(output.id);
    try { setOutputs(await moveOfficialOutput(recordingId, output.id, direction)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not reorder this output."); }
    finally { setBusyId(""); }
  }

  /** Begin editing on deliberate double-click, keeping the saved value until commit succeeds. */
  function beginRename(output: OfficialOutput): void {
    setRenamingId(output.id);
    setDraftName(output.name);
    setRenameError("");
  }

  /** Commit on Enter or blur; duplicate names stay in edit mode with an inline explanation. */
  async function saveRename(output: OfficialOutput): Promise<void> {
    if (renameRequest.current) return;
    const name = draftName.trim();
    if (!name) {
      setRenameError("Stage name cannot be empty.");
      return;
    }
    if (name.toLocaleLowerCase() === "transcription") {
      setRenameError("Transcription is reserved for the transcription output.");
      return;
    }
    const duplicate = outputs.some((item) => item.id !== output.id && item.name.localeCompare(name, undefined, { sensitivity: "accent" }) === 0);
    if (duplicate) {
      setRenameError("This stage name is already used for this recording");
      return;
    }
    if (name === output.name) {
      setRenamingId("");
      setRenameError("");
      return;
    }
    renameRequest.current = true;
    setBusyId(output.id);
    setRenameError("");
    try {
      const renamed = await renameOfficialOutput(recordingId, output.id, name);
      setOutputs((current) => current.map((item) => item.id === renamed.id ? renamed : item));
      setRenamingId("");
    } catch (reason) {
      setRenameError(reason instanceof Error ? reason.message : "Could not rename this stage.");
    } finally {
      renameRequest.current = false;
      setBusyId("");
    }
  }

  /** Toggle one output's text while keeping its title and metadata visible. */
  function toggleBlock(blockId: string): void {
    setCollapsedBlocks((current) => {
      const next = new Set(current);
      if (next.has(blockId)) next.delete(blockId);
      else next.add(blockId);
      return next;
    });
  }

  /** Collapse all known outputs, or expand all when every block is already closed. */
  function toggleAllBlocks(blockIds: string[]): void {
    setCollapsedBlocks(areAllBlocksCollapsed(blockIds, collapsedBlocks) ? new Set() : new Set(blockIds));
  }

  const orderedEditable = outputs.filter((output) => output.kind !== "transcription");
  const outputBlockIds = [
    ...outputs.map((output) => `official:${output.id}`),
    ...history.map((item) => `history:${item.id}`),
  ];
  const allBlocksCollapsed = areAllBlocksCollapsed(outputBlockIds, collapsedBlocks);

  return <section className="details-section recording-run-outputs">
    <div className="recording-runs-heading">
      <div className="section-label">PIPELINE OUTPUTS</div>
      <div className="recording-runs-controls">
        <button className="recording-runs-collapse-all" onClick={() => toggleAllBlocks(outputBlockIds)} disabled={!outputBlockIds.length}
          aria-label={allBlocksCollapsed ? "Expand all output text blocks" : "Collapse all output text blocks"}
          title={allBlocksCollapsed ? "Expand all" : "Collapse all"}>
          {allBlocksCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}{allBlocksCollapsed ? "Expand all" : "Collapse all"}
        </button>
        <button className="recording-runs-refresh" onClick={() => void loadOutputs()} disabled={loading} aria-label="Refresh outputs" title="Refresh outputs">
          {loading ? <LoaderCircle className="spin" size={14} /> : <RefreshCw size={13} />}
        </button>
      </div>
    </div>
    {loading && outputs.length === 0 ? <div className="recording-runs-empty"><LoaderCircle className="spin" size={14} /> Loading official outputs…</div>
      : error && outputs.length === 0 ? <div className="recording-runs-empty recording-runs-error">{error}</div>
      : outputs.length === 0 ? <div className="recording-runs-empty">No official outputs yet. Run a transcription or pipeline to create one.</div>
      : <div className="official-output-list">{outputs.map((output) => {
        const editableIndex = orderedEditable.findIndex((item) => item.id === output.id);
        const blockId = `official:${output.id}`;
        const isCollapsed = collapsedBlocks.has(blockId);
        return <article className="official-output-card" key={output.id}>
          <div className="official-output-heading">
            <div className="official-output-title">
              {output.kind !== "transcription" && renamingId === output.id
                ? <><input
                    className={`official-output-name-input${renameError === "This stage name is already used for this recording" ? " has-conflict" : ""}`}
                    aria-label={`Rename ${output.name}`}
                    aria-invalid={Boolean(renameError)}
                    autoFocus
                    value={draftName}
                    onChange={(event) => { setDraftName(event.target.value); setRenameError(""); }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") { event.preventDefault(); void saveRename(output); }
                      if (event.key === "Escape") { skipRenameBlur.current = true; setRenamingId(""); setRenameError(""); }
                    }}
                    onBlur={() => {
                      if (skipRenameBlur.current) { skipRenameBlur.current = false; return; }
                      void saveRename(output);
                    }}
                    disabled={busyId === output.id}
                  />{renameError && <small className="official-output-name-error" role="alert">{renameError}</small>}</>
                : <b className={output.kind !== "transcription" ? "official-output-name-editable" : undefined}
                    onDoubleClick={() => { if (output.kind !== "transcription") beginRename(output); }}
                    title={output.kind !== "transcription" ? "Double-click to rename" : undefined}>{output.name}</b>}
              <span>{output.kind === "transcription" ? "Transcription" : output.kind}</span>
            </div>
            <div className="official-output-actions">
              {output.kind !== "transcription" && <><button onClick={() => void reorder(output, "up")} disabled={busyId === output.id || editableIndex === 0} aria-label={`Move ${output.name} up`} title="Move up"><ArrowUp size={14} /></button><button onClick={() => void reorder(output, "down")} disabled={busyId === output.id || editableIndex === orderedEditable.length - 1} aria-label={`Move ${output.name} down`} title="Move down"><ArrowDown size={14} /></button></>}
              <button onClick={() => toggleBlock(blockId)} aria-expanded={!isCollapsed} aria-label={`${isCollapsed ? "Expand" : "Collapse"} ${output.name} text`} title={isCollapsed ? "Expand text" : "Collapse text"}>{isCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}</button>
              <button onClick={() => void archive(output)} disabled={busyId === output.id} aria-label={`Move ${output.name} to previous versions`} title="Move to previous versions">{busyId === output.id ? <LoaderCircle className="spin" size={14} /> : <Archive size={14} />}</button>
            </div>
          </div>
          <div className="official-output-meta">{countWords(output.content)} words · {new Date(output.created_at).toLocaleString()}{output.provider ? ` · ${output.provider}` : ""}{output.model ? ` · ${output.model}` : ""}</div>
          {!isCollapsed && (output.kind === "transcription"
            ? <TranscriptContent output={output} recordingId={recordingId} currentTime={audioTime} colorsEnabled={confidenceColorsEnabled} onToggleColors={setConfidenceColorsEnabled} />
            : <pre>{output.content}</pre>)}
        </article>;
      })}</div>}
    {error && outputs.length > 0 && <div className="recording-runs-empty recording-runs-error">{error}</div>}
    <details className="previous-versions">
      <summary>View Previous Versions · {history.length}</summary>
      {history.length === 0 ? <div className="previous-versions-empty">Replaced and removed outputs will appear here.</div>
        : <div className="previous-version-list">{history.map((item) => {
          const blockId = `history:${item.id}`;
          const isCollapsed = collapsedBlocks.has(blockId);
          return <article className="previous-version-card" key={item.id}>
          <div className="previous-version-heading"><b>{item.name}</b><div className="previous-version-actions">
            <button onClick={() => toggleBlock(blockId)} aria-expanded={!isCollapsed} aria-label={`${isCollapsed ? "Expand" : "Collapse"} ${item.name} previous text`} title={isCollapsed ? "Expand text" : "Collapse text"}>{isCollapsed ? <ChevronDown size={14} /> : <ChevronUp size={14} />}</button>
            <button onClick={() => void restore(item)} disabled={busyId === item.id}><RotateCcw size={13} /> Restore</button>
          </div></div>
          <div className="official-output-meta">{countWords(item.content)} words · {item.kind} · {item.archive_reason === "replaced" ? "Replaced" : "Removed"} {new Date(item.archived_at).toLocaleString()}</div>
          <div className="official-output-meta">Stage ran {new Date(item.created_at).toLocaleString()}{item.provider ? ` · ${item.provider}` : ""}{item.model ? ` · ${item.model}` : ""}</div>
          {!isCollapsed && (item.kind === "transcription"
            ? <TranscriptContent output={item} recordingId={recordingId} currentTime={audioTime} colorsEnabled={confidenceColorsEnabled} onToggleColors={setConfidenceColorsEnabled} />
            : <pre>{item.content}</pre>)}
          {restoreId === item.id && <form className="restore-output-form" onSubmit={(event) => { event.preventDefault(); void restore(item, restoreName.trim()); }}>
            <label>This output name is already in use. Choose a new name to restore it.<input autoFocus value={restoreName} onChange={(event) => setRestoreName(event.target.value)} /></label>
            <div><button type="button" onClick={() => setRestoreId("")}>Cancel</button><button type="submit" disabled={!restoreName.trim() || busyId === item.id}>Restore as</button></div>
          </form>}
        </article>})}</div>}
    </details>
  </section>;
}
