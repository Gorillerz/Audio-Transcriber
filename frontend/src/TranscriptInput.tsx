/** Save and review immutable raw transcript versions used as pipeline source input. */
import { useEffect, useState } from "react";
import { LoaderCircle, Save } from "lucide-react";
import { fetchRawTranscripts, saveRawTranscript } from "./api";
import type { RawTranscript } from "./types";

/** Provide a plain-text source editor for imported or fixture transcripts in MVP2. */
export default function TranscriptInput({ recordingId }: { recordingId: string }) {
  const [versions, setVersions] = useState<RawTranscript[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  /** Load version history when the selected recording changes. */
  useEffect(() => {
    let alive = true;
    void fetchRawTranscripts(recordingId).then((items) => {
      if (!alive) return;
      setVersions(items); setText(items[0]?.content ?? ""); setMessage("");
    }).catch((error) => setMessage(error instanceof Error ? error.message : "Could not load transcript."));
    return () => { alive = false; };
  }, [recordingId]);

  /** Append edits as another raw input version so earlier source text remains recoverable. */
  async function save(): Promise<void> {
    setBusy(true);
    try {
      const saved = await saveRawTranscript(recordingId, text);
      setVersions((current) => [saved, ...current]); setMessage(`Saved raw transcript version ${saved.version}.`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not save transcript."); }
    finally { setBusy(false); }
  }

  return <section className="details-section transcript-input"><div className="section-label">RAW TRANSCRIPT INPUT</div><p>Paste an existing transcript or a fixture here. Saving creates a version and preserves earlier versions.</p><textarea aria-label="Raw transcript text" value={text} onChange={(event) => setText(event.target.value)} placeholder="Paste transcript text to use in a pipeline…" rows={7} /><button className="quiet-button" onClick={() => void save()} disabled={busy || !text.trim()}>{busy ? <LoaderCircle className="spin" size={14} /> : <Save size={14} />} Save as new version</button>{message && <small>{message}</small>}{versions.length > 1 && <details><summary>Previous versions ({versions.length - 1})</summary>{versions.slice(1).map((version) => <article key={version.id}><b>Version {version.version}</b><pre>{version.content}</pre></article>)}</details>}</section>;
}
