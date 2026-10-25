/** Main MVP1 recording catalog, import flow, and selected-recording details panel. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AudioLines, Check, ChevronDown, ChevronRight, CircleHelp, Clock3, FileAudio, FileUp, Filter, FolderOpen, FolderPlus, Headphones, ListFilter, LoaderCircle, Music2, Search, Settings2, ShieldCheck, SlidersHorizontal, Trash2, Upload, Workflow, X } from "lucide-react";
import { addToGroup, confirmMatch, confirmSeparate, createGroup, deleteRecordings, fetchGroups, fetchOpenRouterModels, fetchRecordings, importFiles, updateStatus } from "./api";
import { filterAndSort, formatDate, formatDuration, type DurationFilter, type SortKey } from "./catalog";
import type { Recording, RecordingGroup } from "./types";
import PipelineManager from "./PipelineManager";
import ApiKeySettings from "./ApiKeySettings";
import RecordingRunOutputs from "./RecordingRunOutputs";
import TranscriptionLauncher from "./TranscriptionLauncher";
import RecordingAudioPlayer from "./RecordingAudioPlayer";

type StatusFilter = "all" | "untranscribed" | "transcribed";

/** Limit the details panel to half of the space remaining beside the library. */
function maxDetailsPanelWidth(): number {
  const sidebarWidth = document.querySelector(".sidebar")?.getBoundingClientRect().width ?? 242;
  return Math.max(280, Math.floor((window.innerWidth - sidebarWidth - 8) / 2));
}

/** Render the library shell and keep catalog, selection, and import feedback in sync. */
export default function App() {
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [groups, setGroups] = useState<RecordingGroup[]>([]);
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null);
  const [groupDialogOpen, setGroupDialogOpen] = useState(false);
  const [groupName, setGroupName] = useState("");
  const [workflowOpen, setWorkflowOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [transcriptionRecordingId, setTranscriptionRecordingId] = useState<string | null>(null);
  const [workflowRecordingIds, setWorkflowRecordingIds] = useState<string[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [status, setStatus] = useState<StatusFilter>("all");
  const [duration, setDuration] = useState<DurationFilter>("all");
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("media_date");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");
  const [checkedIds, setCheckedIds] = useState<string[]>([]);
  const [pendingDeleteIds, setPendingDeleteIds] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const [detailsPanelWidth, setDetailsPanelWidth] = useState(318);
  const detailsResizeStart = useRef<{ x: number; width: number } | null>(null);

  /** Keep a resized panel within the equal-width limit when the window changes size. */
  useEffect(() => {
    const fitPanel = () => setDetailsPanelWidth((width) => Math.min(width, maxDetailsPanelWidth()));
    window.addEventListener("resize", fitPanel);
    return () => window.removeEventListener("resize", fitPanel);
  }, []);

  /** Load the persisted catalog so refreshing the page keeps library state. */
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [rows, savedGroups] = await Promise.all([fetchRecordings(), fetchGroups()]);
      setRecordings(rows);
      setGroups(savedGroups);
      setError("");
      setSelectedId((current) => current && rows.some((row) => row.id === current) ? current : rows[0]?.id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not connect to the local library service.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { void fetchOpenRouterModels().catch(() => undefined); }, []);

  /** Upload supported audio files and summarize partial errors without hiding successes. */
  const handleImport = useCallback(async (files: File[]) => {
    if (!files.length) return;
    setImporting(true);
    setToast("");
    try {
      const result = await importFiles(files);
      await refresh();
      const newRecording = result.imported.find((item) => !item.duplicate)?.recording;
      if (newRecording) setSelectedId(newRecording.id);
      const duplicates = result.imported.filter((item) => item.duplicate).length;
      const matches = result.imported.filter((item) => item.possible_matches.length).length;
      const pieces = [`${result.imported.length} file${result.imported.length === 1 ? "" : "s"} added`];
      if (duplicates) pieces.push(`${duplicates} already in library`);
      if (matches) pieces.push(`${matches} possible match${matches === 1 ? "" : "es"} to review`);
      if (result.errors.length) pieces.push(`${result.errors.length} could not be imported`);
      setToast(pieces.join(" · "));
      if (result.errors.length) setError(result.errors.map((item) => `${item.name}: ${item.error}`).join("\n"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Import failed. Please try again.");
    } finally {
      setImporting(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  }, [refresh]);

  const visibleRows = useMemo(() => filterAndSort(recordings.filter((row) => !activeGroupId || row.group_ids.includes(activeGroupId)), status, duration, query, sortKey, sortDirection), [recordings, activeGroupId, status, duration, query, sortKey, sortDirection]);
  const selected = recordings.find((row) => row.id === selectedId) ?? null;
  const transcriptionRecording = recordings.find((row) => row.id === transcriptionRecordingId) ?? null;
  const possibleMatch = selected?.possible_match_id ? recordings.find((row) => row.id === selected.possible_match_id) ?? null : null;
  const totalSeconds = recordings.reduce((sum, row) => sum + (row.duration_seconds ?? 0), 0);
  const pendingCount = recordings.filter((row) => row.status === "untranscribed").length;

  /** Toggle an item independently of its row selection/details action. */
  function toggleChecked(id: string): void {
    setCheckedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  /** Open the reusable workflow editor with an optional single or batch selection. */
  function openWorkflows(ids: string[]): void {
    setWorkflowRecordingIds(ids); setWorkflowOpen(true);
  }

  /** Move confirmed recordings to the OS trash, then refresh the catalog. */
  async function confirmDelete(): Promise<void> {
    try {
      const result = await deleteRecordings(pendingDeleteIds);
      setPendingDeleteIds([]);
      setCheckedIds((current) => current.filter((id) => !result.deleted.includes(id)));
      await refresh();
      setToast(`${result.deleted.length} recording${result.deleted.length === 1 ? "" : "s"} moved to the Recycle Bin.`);
      if (result.errors.length) setError(result.errors.map((item) => item.error).join("\n"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not move recordings to the Recycle Bin.");
    }
  }

  /** Create a named group and include the currently checked recordings. */
  async function saveNewGroup(): Promise<void> {
    try {
      const group = await createGroup(groupName, checkedIds);
      setGroupName(""); setGroupDialogOpen(false); setActiveGroupId(group.id); setStatus("all"); setCheckedIds([]);
      await refresh(); setToast(`Created “${group.name}”.`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not create group."); }
  }

  /** Add checked recordings to an existing group and refresh its count. */
  async function addCheckedToGroup(group: RecordingGroup): Promise<void> {
    try {
      await addToGroup(group.id, checkedIds); setGroupDialogOpen(false); setActiveGroupId(group.id); setStatus("all"); setCheckedIds([]);
      await refresh(); setToast(`Added recordings to “${group.name}”.`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not add recordings to group."); }
  }

  /** Toggle a column between ascending and descending order. */
  function sortBy(key: SortKey): void {
    if (sortKey === key) setSortDirection((current) => current === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDirection(key === "media_date" ? "desc" : "asc"); }
  }

  /** Resolve an ambiguous metadata match only after an explicit user choice. */
  async function resolvePossibleMatch(asSame: boolean): Promise<void> {
    if (!selected?.possible_match_id) return;
    try {
      if (asSame) await confirmMatch(selected.id, selected.possible_match_id);
      else await confirmSeparate(selected.id);
      await refresh();
      setToast(asSame ? "Files linked to the same recording." : "Marked as a separate recording.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update the possible match.");
    }
  }

  /** Let the user migrate known transcript status before legacy JSON import exists. */
  async function changeStatus(nextStatus: Recording["status"]): Promise<void> {
    if (!selected) return;
    try {
      await updateStatus(selected.id, nextStatus);
      await refresh();
      setToast(nextStatus === "transcribed" ? "Marked as already transcribed." : "Marked as not transcribed.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update transcription status.");
    }
  }

  return (
    <div className="app-shell" onDragEnter={(event) => { event.preventDefault(); setDragging(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={(event) => { if (event.currentTarget === event.target) setDragging(false); }} onDrop={(event) => { event.preventDefault(); setDragging(false); void handleImport(Array.from(event.dataTransfer.files)); }}>
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark"><AudioLines size={20} strokeWidth={2.3} /></div><div><strong>still</strong><span>JOURNAL ARCHIVE</span></div></div>
        <div className="workspace-label">YOUR LIBRARY</div>
        <nav className="nav-list" aria-label="Library views">
          <button className={`nav-item ${status === "all" && !activeGroupId ? "active" : ""}`} onClick={() => { setActiveGroupId(null); setStatus("all"); }}><FolderOpen size={17} /><span>All recordings</span><span className="nav-count">{recordings.length}</span></button>
          <button className={`nav-item ${status === "untranscribed" && !activeGroupId ? "active" : ""}`} onClick={() => { setActiveGroupId(null); setStatus("untranscribed"); }}><span className="nav-dot pending-dot" /><span>Needs transcription</span><span className="nav-count">{pendingCount}</span></button>
          <button className={`nav-item ${status === "transcribed" && !activeGroupId ? "active" : ""}`} onClick={() => { setActiveGroupId(null); setStatus("transcribed"); }}><span className="nav-dot done-dot" /><span>Transcribed</span><span className="nav-count">{recordings.length - pendingCount}</span></button>
        </nav>
        <div className="groups-heading"><span>GROUPS</span><button aria-label="Create group" title="Create group" onClick={() => { setCheckedIds([]); setGroupDialogOpen(true); }}><FolderPlus size={15} /></button></div>
        <nav className="nav-list group-nav" aria-label="Recording groups">{groups.map((group) => <button key={group.id} className={`nav-item ${activeGroupId === group.id ? "active" : ""}`} onClick={() => { setActiveGroupId(group.id); setStatus("all"); }}><FolderOpen size={16} /><span>{group.name}</span><span className="nav-count">{group.recording_count}</span></button>)}</nav>
        <div className="workflow-nav"><button className="nav-item" onClick={() => openWorkflows(checkedIds)}><Workflow size={17} /><span>Pipeline Workflows</span></button></div>
        <div className="sidebar-bottom"><div className="local-card"><div className="local-icon"><ShieldCheck size={17} /></div><div><b>Stored on this device</b><span>Your recordings stay in your local library.</span></div></div><button className="settings-link" onClick={() => setSettingsOpen(true)}><Settings2 size={16} /> Library settings <ChevronRight size={15} /></button><div className="sidebar-footer">MVP 1.0 <span>·</span> PRIVATE BY DESIGN</div></div>
      </aside>

      <main className="main-area">
        <header className="topbar"><div className="breadcrumb">Library <ChevronRight size={14} /><b>Audio recordings</b></div><div className="topbar-right"><span className="local-status"><span /> Local library</span><button className="icon-button" aria-label="Help"><CircleHelp size={18} /></button></div></header>
        <div className="content-wrap">
          <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> YOUR PERSONAL ARCHIVE</div><h1>Audio Library</h1></div><button className="primary-button" onClick={() => inputRef.current?.click()} disabled={importing}><FileUp size={17} />{importing ? "Importing…" : "Import recordings"}</button><input ref={inputRef} type="file" multiple accept=".mp3,.m4a,.wav,.flac,.ogg,.opus,.aac,.wma,.webm,.mp4,audio/*" hidden onChange={(event) => void handleImport(Array.from(event.target.files ?? []))} /></section>

          <section className="stats-grid" aria-label="Library summary">
            <article className="stat-card"><div className="stat-icon lilac"><Music2 size={17} /></div><div><span>Total Recordings</span><strong>{recordings.length.toLocaleString()}</strong></div></article>
            <article className="stat-card"><div className="stat-icon amber"><Clock3 size={17} /></div><div><span>To Transcribe</span><strong>{pendingCount.toLocaleString()}</strong></div></article>
            <article className="stat-card"><div className="stat-icon mint"><Headphones size={17} /></div><div><span>Audio Time</span><strong>{formatDuration(totalSeconds)}</strong></div></article>
          </section>

          <section className="library-card">
            <div className="library-card-heading"><div><h2>{activeGroupId ? groups.find((group) => group.id === activeGroupId)?.name : "Your Recordings"} <span className="result-count">{visibleRows.length}</span></h2></div><div className="card-actions">{checkedIds.length > 0 && <><button className="quiet-button" onClick={() => setGroupDialogOpen(true)}><FolderPlus size={14} /> Add to Group</button><button className="quiet-button" onClick={() => openWorkflows(checkedIds)}><Workflow size={14} /> Run Pipeline</button><button className="quiet-button delete-selected" onClick={() => setPendingDeleteIds(checkedIds)}><Trash2 size={14} /> Move {checkedIds.length} to Recycle Bin</button></>}<button className="quiet-button" onClick={() => void refresh()} aria-label="Refresh catalog"><LoaderCircle className={loading ? "spin" : ""} size={16} /> Refresh</button></div></div>
            <div className="toolbar"><label className="search-box"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search recordings" /></label><div className="filter-controls"><span className="filter-label"><SlidersHorizontal size={14} /> FILTERS</span><label className="select-wrap"><Filter size={14} /><select aria-label="Filter by duration" value={duration} onChange={(event) => setDuration(event.target.value as DurationFilter)}><option value="all">Any length</option><option value="under10">Under 10 min</option><option value="10to40">10–40 min</option><option value="over40">Over 40 min</option></select><ChevronDown size={13} /></label><label className="select-wrap"><ListFilter size={14} /><select aria-label="Filter by transcription status" value={status} onChange={(event) => setStatus(event.target.value as StatusFilter)}><option value="all">Any status</option><option value="untranscribed">Not transcribed</option><option value="transcribed">Transcribed</option></select><ChevronDown size={13} /></label></div></div>

            {toast && <div className="notice success-notice"><Check size={15} /><span>{toast}</span><button aria-label="Dismiss message" onClick={() => setToast("")}><X size={15} /></button></div>}
            {error && <div className="notice error-notice"><CircleHelp size={15} /><span>{error.split("\n").map((line, index) => <span key={index}>{line}{index < error.split("\n").length - 1 && <br />}</span>)}</span><button aria-label="Dismiss error" onClick={() => setError("")}><X size={15} /></button></div>}

            <div className="table-scroll"><table><thead><tr><th className="check-col"><input aria-label="Select all visible recordings" type="checkbox" checked={visibleRows.length > 0 && visibleRows.every((row) => checkedIds.includes(row.id))} onChange={(event) => setCheckedIds(event.target.checked ? [...new Set([...checkedIds, ...visibleRows.map((row) => row.id)])] : checkedIds.filter((id) => !visibleRows.some((row) => row.id === id)))} /></th><th className="name-col"><SortButton label="Recording" sortKey="original_name" activeKey={sortKey} direction={sortDirection} onClick={sortBy} /></th><th><SortButton label="Duration" sortKey="duration_seconds" activeKey={sortKey} direction={sortDirection} onClick={sortBy} /></th><th><SortButton label="Date" sortKey="media_date" activeKey={sortKey} direction={sortDirection} onClick={sortBy} /></th><th className="group-col">Group</th><th><SortButton label="Status" sortKey="status" activeKey={sortKey} direction={sortDirection} onClick={sortBy} /></th><th aria-label="Details" /></tr></thead>
              <tbody>
                {loading && recordings.length === 0 ? <tr><td colSpan={7}><div className="table-loading"><LoaderCircle className="spin" size={20} /> Connecting to your local library…</div></td></tr> : visibleRows.length ? visibleRows.map((row) => <tr key={row.id} className={`${row.status === "untranscribed" ? "row-pending" : ""} ${selectedId === row.id ? "row-selected" : ""}`} onClick={() => setSelectedId(row.id)} tabIndex={0} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setSelectedId(row.id); }}>
                  <td className="check-cell"><input aria-label={`Select ${row.original_name}`} type="checkbox" checked={checkedIds.includes(row.id)} onClick={(event) => event.stopPropagation()} onChange={() => toggleChecked(row.id)} /></td><td><div className="recording-cell"><div className={`file-icon ${row.extension === ".wav" ? "wav" : ""}`}><FileAudio size={17} /></div><div className="recording-name-wrap"><span className="recording-name" title={row.original_name}>{row.original_name}</span><span className="recording-sub">{row.extension.replace(".", "").toUpperCase()} recording{row.alias_count ? ` · ${row.alias_count} known name${row.alias_count > 1 ? "s" : ""}` : ""}</span></div></div></td>
                  <td><span className="duration-value">{formatDuration(row.duration_seconds)}</span></td><td><span className="date-value">{formatDate(row.media_date)}</span></td><td><GroupLabels recording={row} groups={groups} /></td><td><StatusPill recording={row} /></td><td><button className="row-more" aria-label={`Open ${row.original_name} details`} onClick={(event) => { event.stopPropagation(); setSelectedId(row.id); }}><ChevronRight size={17} /></button></td>
                </tr>) : <tr><td colSpan={7}><EmptyState hasAny={recordings.length > 0} importing={importing} onImport={() => inputRef.current?.click()} /></td></tr>}
              </tbody></table></div>
            <div className="table-footer"><span>Showing <b>{visibleRows.length}</b> of <b>{recordings.length}</b> recordings</span></div>
          </section>
        </div>
      </main>

      {selected && <div className="details-panel-resizer" role="separator" aria-label="Resize recording details panel" aria-orientation="vertical" aria-valuemin={280} aria-valuemax={maxDetailsPanelWidth()} aria-valuenow={detailsPanelWidth} tabIndex={0} onPointerDown={(event) => { detailsResizeStart.current = { x: event.clientX, width: detailsPanelWidth }; event.currentTarget.setPointerCapture(event.pointerId); }} onPointerMove={(event) => { if (!detailsResizeStart.current) return; setDetailsPanelWidth(Math.max(280, Math.min(maxDetailsPanelWidth(), detailsResizeStart.current.width + detailsResizeStart.current.x - event.clientX))); }} onPointerUp={(event) => { detailsResizeStart.current = null; event.currentTarget.releasePointerCapture(event.pointerId); }} onKeyDown={(event) => { if (event.key === "ArrowLeft") setDetailsPanelWidth((width) => Math.min(maxDetailsPanelWidth(), width + 20)); if (event.key === "ArrowRight") setDetailsPanelWidth((width) => Math.max(280, width - 20)); }} />}
      {selected && <aside className="details-panel" style={{ "--details-panel-width": `${detailsPanelWidth}px` } as React.CSSProperties} aria-label="Recording details"><div className="details-top"><span>RECORDING DETAILS</span><button className="icon-button close-details" aria-label="Close details" onClick={() => setSelectedId(null)}><X size={18} /></button></div><div className="details-scroll">
        <div className="details-section"><div className="section-label">FILE INFORMATION</div><DetailRow label="File name" value={selected.original_name} /><DetailRow label="Duration" value={formatDuration(selected.duration_seconds)} /><DetailRow label="Date recorded" value={formatDate(selected.media_date)} /><DetailRow label="File size" value={formatBytes(selected.size_bytes)} /><DetailRow label="Format" value={selected.extension.replace(".", "").toUpperCase()} /><DetailRow label="Date added" value={new Date(selected.imported_at).toLocaleString()} /><div className="details-file-identity"><div className="hash-label">CONTENT FINGERPRINT</div><code className="hash-value">{selected.sha256.slice(0, 22)}…</code>{selected.aliases?.length ? <div className="alias-list"><div className="hash-label">CONFIRMED FILE NAMES</div>{selected.aliases.map((alias) => <div className="alias-item" key={alias.sha256}><Check size={13} /> {alias.original_name}</div>)}</div> : null}</div></div>
        {possibleMatch && <div className="match-card"><div className="match-title"><CircleHelp size={16} /><b>Possible match</b></div><p>This file resembles <strong>{possibleMatch.original_name}</strong> by size and duration. Confirm whether they’re the same recording.</p><div className="match-actions"><button onClick={() => void resolvePossibleMatch(true)}>Same recording</button><button onClick={() => void resolvePossibleMatch(false)}>Keep separate</button></div></div>}
        <RecordingAudioPlayer recording={selected} />
        <RecordingRunOutputs recordingId={selected.id} />
      </div><div className="details-bottom"><button className="detail-action" onClick={() => void changeStatus(selected.status === "transcribed" ? "untranscribed" : "transcribed")}><Check size={16} />{selected.status === "transcribed" ? "Mark not transcribed" : "Mark as already transcribed"}</button><button className="detail-action" onClick={() => openWorkflows([selected.id])}><Workflow size={16} /> Run Pipeline</button><button className="detail-action" onClick={() => setPendingDeleteIds([selected.id])}><Trash2 size={16} /> Move to Recycle Bin</button><button className="detail-action" onClick={() => setTranscriptionRecordingId(selected.id)}><AudioLines size={16} /> Start transcription</button></div></aside>}

      {pendingDeleteIds.length > 0 && <div className="confirm-overlay" role="presentation"><section className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="delete-title"><div className="confirm-icon"><Trash2 size={20} /></div><h2 id="delete-title">Move {pendingDeleteIds.length === 1 ? "recording" : `${pendingDeleteIds.length} recordings`} to the Recycle Bin?</h2><p>The selected audio {pendingDeleteIds.length === 1 ? "file will" : "files will"} be moved to your computer’s Recycle Bin. You can restore {pendingDeleteIds.length === 1 ? "it" : "them"} from there.</p><div className="confirm-actions"><button className="quiet-button" onClick={() => setPendingDeleteIds([])}>Cancel</button><button className="confirm-delete" onClick={() => void confirmDelete()}><Trash2 size={15} /> Move to Recycle Bin</button></div></section></div>}

      {groupDialogOpen && <div className="confirm-overlay" role="presentation"><section className="confirm-dialog group-dialog" role="dialog" aria-modal="true" aria-labelledby="group-title"><div className="confirm-icon group-icon"><FolderPlus size={20} /></div><h2 id="group-title">Add {checkedIds.length ? `${checkedIds.length} recording${checkedIds.length === 1 ? "" : "s"} to a group` : "a group"}</h2><label className="group-name-field">New group name<input autoFocus value={groupName} onChange={(event) => setGroupName(event.target.value)} placeholder="For example, Travel" onKeyDown={(event) => { if (event.key === "Enter" && groupName.trim()) void saveNewGroup(); }} /></label><button className="confirm-delete create-group-button" disabled={!groupName.trim()} onClick={() => void saveNewGroup()}><FolderPlus size={15} /> Create group{checkedIds.length ? " and add recordings" : ""}</button>{groups.length > 0 && <><div className="group-picker-label">OR ADD TO AN EXISTING GROUP</div><div className="group-picker-list">{groups.map((group) => <button key={group.id} onClick={() => void addCheckedToGroup(group)} disabled={checkedIds.length === 0}><span><FolderOpen size={15} />{group.name}</span><span>{group.recording_count} <ChevronRight size={14} /></span></button>)}</div></>}<div className="confirm-actions"><button className="quiet-button" onClick={() => { setGroupDialogOpen(false); setGroupName(""); }}>Cancel</button></div></section></div>}

      <PipelineManager open={workflowOpen} recordingIds={workflowRecordingIds} onClose={() => { setWorkflowOpen(false); setWorkflowRecordingIds([]); }} />
      <ApiKeySettings open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      {transcriptionRecording && <TranscriptionLauncher recording={transcriptionRecording} onClose={() => setTranscriptionRecordingId(null)} onComplete={() => { void refresh(); }} />}

      {dragging && <div className="drop-overlay"><div className="drop-card"><div><FileUp size={30} /></div><h2>Drop recordings to import</h2><p>Your files will be copied to the local library.</p></div></div>}
    </div>
  );
}

/** Render a sortable table heading with a visible active direction indicator. */
function SortButton({ label, sortKey, activeKey, direction, onClick }: { label: string; sortKey: SortKey; activeKey: SortKey; direction: "asc" | "desc"; onClick: (key: SortKey) => void }) {
  return <button className={`sort-button ${activeKey === sortKey ? "sort-active" : ""}`} onClick={() => onClick(sortKey)}>{label}<span>{activeKey === sortKey ? direction === "asc" ? "↑" : "↓" : "↕"}</span></button>;
}

/** Display transcription state with both text and a shape/color cue. */
function StatusPill({ recording, large = false }: { recording: Recording; large?: boolean }) {
  const isDone = recording.status === "transcribed";
  return <span className={`status-pill ${isDone ? "status-done" : "status-pending"} ${large ? "status-large" : ""}`}><span className="status-indicator">{isDone ? <Check size={10} /> : <span />}</span>{isDone ? "Transcribed" : "Not transcribed"}</span>;
}

/** Show the assigned groups compactly while keeping ungrouped rows identifiable. */
function GroupLabels({ recording, groups }: { recording: Recording; groups: RecordingGroup[] }) {
  const names = groups.filter((group) => recording.group_ids.includes(group.id)).map((group) => group.name);
  return names.length ? <span className="recording-groups" title={names.join(", ")}>{names.join(", ")}</span> : <span className="no-group">—</span>;
}

/** Show a compact metadata label and value in the details panel. */
function DetailRow({ label, value }: { label: string; value: string }) {
  return <div className="detail-row"><span>{label}</span><b>{value}</b></div>;
}

/** Offer import again when filters are empty or the library has no recordings. */
function EmptyState({ hasAny, importing, onImport }: { hasAny: boolean; importing: boolean; onImport: () => void }) {
  return <div className="empty-state"><div className="empty-illustration"><div className="empty-orbit orbit-one" /><div className="empty-orbit orbit-two" /><div className="empty-note"><AudioLines size={24} /></div><div className="empty-spark spark-one">✦</div><div className="empty-spark spark-two">✳</div></div><h3>{hasAny ? "No recordings match these filters" : "Your library is ready"}</h3><p>{hasAny ? "Try changing your search or filters." : "Bring in your voice notes to start building your archive."}</p>{!hasAny && <button className="empty-button" onClick={onImport} disabled={importing}><Upload size={16} /> Import audio files</button>}<div className="empty-hint"><span /> .mp3 <span /> .m4a <span /> .wav <span /> .flac</div></div>;
}

/** Format byte counts into a human-readable value for the metadata panel. */
function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
