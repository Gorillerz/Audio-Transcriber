/** Settings dialog for entering and managing the OpenRouter API credential. */
import { useEffect, useState } from "react";
import { Check, Eye, EyeOff, KeyRound, LoaderCircle, X } from "lucide-react";
import { deleteOpenRouterKey, fetchOpenRouterKeyStatus, saveOpenRouterKey, testOpenRouterKey, type OpenRouterKeyStatus } from "./api";

/** Keep the secret in the form only and show availability/source from the local API. */
export default function ApiKeySettings({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [status, setStatus] = useState<OpenRouterKeyStatus | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [connectionResult, setConnectionResult] = useState<{ valid: boolean; message: string } | null>(null);

  useEffect(() => {
    if (!open) return;
    setApiKey("");
    setMessage("");
    setError("");
    setConnectionResult(null);
    void fetchOpenRouterKeyStatus().then(setStatus).catch((reason: Error) => setError(reason.message));
  }, [open]);

  /** Save once and discard the value from React state after the API confirms. */
  async function save() {
    if (!apiKey.trim()) return;
    setBusy(true); setError(""); setMessage("");
    try {
      setStatus(await saveOpenRouterKey(apiKey));
      setApiKey("");
      setRevealed(false);
      setMessage("API key saved to Windows Credential Manager.");
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  /** Delete only the key saved by this dialog; an environment key can remain active. */
  async function remove() {
    setBusy(true); setError(""); setMessage("");
    try {
      setStatus(await deleteOpenRouterKey());
      setMessage(status?.source === "environment variable" ? "Saved key removed. The environment key is still active." : "Saved API key removed.");
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  /** Check a typed key before saving, or test the currently active stored key. */
  async function testConnection() {
    setBusy(true); setError(""); setMessage(""); setConnectionResult(null);
    try { setConnectionResult(await testOpenRouterKey(apiKey.trim() || undefined)); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  }

  if (!open) return null;
  return <div className="confirm-overlay settings-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section className="confirm-dialog api-settings-dialog" role="dialog" aria-modal="true" aria-labelledby="api-settings-title">
      <header className="settings-dialog-header"><div className="confirm-icon group-icon"><KeyRound size={20} /></div><button className="icon-button" aria-label="Close settings" onClick={onClose}><X size={18} /></button></header>
      <h2 id="api-settings-title">OpenRouter API Key</h2>
      <p>Save your key in Windows Credential Manager. The app uses it for pipeline stages and never stores it in the library database.</p>
      <div className={`key-status ${status?.configured ? "key-configured" : ""}`}>
        <span className="key-status-dot" />
        <span className="key-status-text">{status ? status.configured ? status.source === "Windows Credential Manager" ? "A key is currently active. It is stored in Windows Credential Manager." : "A key is currently active from the environment variable." : "No API key configured" : <><LoaderCircle size={13} className="spin" /> Checking settings…</>}</span>
        <button className="settings-green-button test-connection-button" disabled={busy || (!apiKey.trim() && !status?.configured)} onClick={() => void testConnection()}>{busy && <LoaderCircle className="spin" size={14} />}Test Connection</button>
      </div>
      <div className="api-key-row"><label className="api-key-field">{status?.configured ? "Replace API key" : "API key"}
        <span className="api-key-input-wrap"><input autoFocus type={revealed ? "text" : "password"} autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="sk-or-v1-…" onKeyDown={(event) => { if (event.key === "Enter") void save(); }} /><button type="button" aria-label={revealed ? "Hide API key" : "Show API key"} onClick={() => setRevealed((value) => !value)}><span>{revealed ? <EyeOff size={16} /> : <Eye size={16} />}</span></button></span>
      </label><button className="settings-green-button save-key-button" disabled={busy || !apiKey.trim()} onClick={() => void save()}>{busy && <LoaderCircle className="spin" size={14} />}Save Key</button></div>
      {message && <div className="settings-message"><Check size={14} />{message}</div>}
      {connectionResult && <div className={connectionResult.valid ? "settings-message" : "settings-error"}>{connectionResult.valid && <Check size={14} />}{connectionResult.message}</div>}
      {error && <div className="settings-error">{error}</div>}
      <div className="settings-footer">{status?.configured && status.source === "Windows Credential Manager" ? <button className="settings-red-button remove-key-button" disabled={busy} onClick={() => void remove()}>Remove Saved Key</button> : <span /> }<button className="settings-green-button done-button" onClick={onClose}>Done</button></div>
    </section>
  </div>;
}
