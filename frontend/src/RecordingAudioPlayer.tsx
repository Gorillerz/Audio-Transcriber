/** Recording-side audio controls, waveform seeking, and timed transcript playback events. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FastForward, LoaderCircle, Pause, Play, Rewind, Volume2 } from "lucide-react";
import { fetchRecordingWaveform } from "./api";
import { clampPlaybackRate, formatDuration, seekTarget } from "./catalog";
import type { Recording, RecordingWaveform } from "./types";
import "./RecordingAudioPlayer.css";

type SourceMode = "original" | "converted";
const playbackRates = [1, 1.25, 1.5, 1.75, 2];

/** Pick the browser MIME hint from the recorded format when metadata is absent or generic. */
function recordingMime(recording: Recording): string {
  if (recording.mime_type && recording.mime_type !== "application/octet-stream") return recording.mime_type;
  const known: Record<string, string> = { ".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".aac": "audio/aac", ".m4a": "audio/mp4", ".mp4": "audio/mp4", ".webm": "audio/webm", ".wma": "audio/x-ms-wma" };
  return known[recording.extension.toLocaleLowerCase()] ?? "";
}

/** Keep native browser support first and lazily request a cached MP3 only as a fallback. */
function browserCanPlay(recording: Recording): boolean {
  const audio = document.createElement("audio");
  const mime = recordingMime(recording);
  return !mime || audio.canPlayType(mime) !== "";
}

/** Draw a compact amplitude envelope and shade the section already played. */
function paintWaveform(canvas: HTMLCanvasElement, waveform: RecordingWaveform, progress: number): void {
  const bounds = canvas.getBoundingClientRect();
  if (!bounds.width || !bounds.height) return;
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.round(bounds.width * ratio);
  canvas.height = Math.round(bounds.height * ratio);
  const context = canvas.getContext("2d");
  if (!context) return;
  context.scale(ratio, ratio);
  context.clearRect(0, 0, bounds.width, bounds.height);
  const count = Math.max(1, Math.floor(bounds.width / 3));
  const step = waveform.peaks.length / count;
  const mid = bounds.height / 2;
  const progressX = bounds.width * Math.max(0, Math.min(1, progress));
  for (let index = 0; index < count; index += 1) {
    const from = Math.floor(index * step);
    const to = Math.max(from + 1, Math.floor((index + 1) * step));
    let peak = 0;
    for (let cursor = from; cursor < Math.min(to, waveform.peaks.length); cursor += 1) peak = Math.max(peak, waveform.peaks[cursor] ?? 0);
    const height = Math.max(2, peak * (bounds.height - 4));
    const x = index * 3 + 0.5;
    context.fillStyle = x < progressX ? "#7458e8" : "#d8d5e3";
    context.beginPath();
    context.roundRect(x, mid - height / 2, 1.8, height, 1);
    context.fill();
  }
}

/** Play the selected source, expose seek/rate controls, and synchronize timed transcript clicks. */
export default function RecordingAudioPlayer({ recording }: { recording: Recording }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [waveform, setWaveform] = useState<RecordingWaveform | null>(null);
  const [waveformError, setWaveformError] = useState("");
  const [currentTime, setCurrentTime] = useState(0);
  const [mediaDuration, setMediaDuration] = useState(recording.duration_seconds ?? 0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [sourceMode, setSourceMode] = useState<SourceMode>(() => browserCanPlay(recording) ? "original" : "converted");
  const [sourceError, setSourceError] = useState("");
  const [converting, setConverting] = useState(false);

  const sourceUrl = useMemo(() => sourceMode === "original"
    ? `/api/recordings/${recording.id}/audio`
    : `/api/recordings/${recording.id}/audio/playback`, [recording.id, sourceMode]);

  useEffect(() => {
    let active = true;
    setWaveform(null);
    setWaveformError("");
    setCurrentTime(0);
    setMediaDuration(recording.duration_seconds ?? 0);
    setRate(1);
    setPlaying(false);
    setSourceMode(browserCanPlay(recording) ? "original" : "converted");
    setSourceError("");
    setConverting(!browserCanPlay(recording));
    void fetchRecordingWaveform(recording.id).then((result) => { if (active) setWaveform(result); })
      .catch((error: unknown) => { if (active) setWaveformError(error instanceof Error ? error.message : "Waveform could not be loaded."); });
    return () => { active = false; audioRef.current?.pause(); };
  }, [recording.id]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.playbackRate = rate;
    if (sourceMode === "converted") setConverting(true);
  }, [rate, sourceMode, sourceUrl]);

  useEffect(() => {
    if (!waveform || !canvasRef.current) return;
    const draw = () => { if (canvasRef.current) paintWaveform(canvasRef.current, waveform, currentTime / (mediaDuration || waveform.duration_seconds || 1)); };
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(canvasRef.current);
    return () => observer.disconnect();
  }, [currentTime, mediaDuration, waveform]);

  const seek = useCallback((time: number) => {
    const audio = audioRef.current;
    if (!audio || !Number.isFinite(time)) return;
    const duration = Number.isFinite(audio.duration) ? audio.duration : mediaDuration;
    audio.currentTime = seekTarget(0, time, duration || time);
    setCurrentTime(audio.currentTime);
    window.dispatchEvent(new CustomEvent("journal:audio-time", { detail: { recordingId: recording.id, time: audio.currentTime } }));
  }, [mediaDuration, recording.id]);

  useEffect(() => {
    const onTranscriptSeek = (event: Event) => {
      const detail = (event as CustomEvent<{ recordingId: string; time: number; play?: boolean }>).detail;
      if (detail?.recordingId !== recording.id) return;
      seek(detail.time);
      if (detail.play) void audioRef.current?.play().catch(() => setSourceError("The browser could not start audio playback."));
    };
    window.addEventListener("journal:audio-seek", onTranscriptSeek);
    return () => window.removeEventListener("journal:audio-seek", onTranscriptSeek);
  }, [recording.id, seek]);

  /** Seek through keyboard or pointer input, using the same clamping rule as the skip buttons. */
  function onWaveformPointer(event: React.PointerEvent<HTMLCanvasElement>): void {
    const bounds = event.currentTarget.getBoundingClientRect();
    const duration = mediaDuration || waveform?.duration_seconds || 0;
    if (duration > 0) seek(((event.clientX - bounds.left) / bounds.width) * duration);
  }

  /** Start playback and surface browser permission/device errors in this player. */
  async function togglePlayback(): Promise<void> {
    const audio = audioRef.current;
    if (!audio) return;
    if (!audio.paused) { audio.pause(); return; }
    try { await audio.play(); setSourceError(""); }
    catch { setSourceError("The browser could not start audio playback. Check that the recording is available."); }
  }

  /** Retry once through a cached MP3 when the native decoder rejects the original format. */
  function handleAudioError(): void {
    if (sourceMode === "original") {
      setSourceMode("converted");
      setConverting(true);
      setSourceError("");
    } else {
      setConverting(false);
      setSourceError("Audio could not be played. Check that FFmpeg is installed and the source file is available.");
    }
  }

  const duration = mediaDuration || waveform?.duration_seconds || 0;
  return <section className="recording-audio-player" aria-label={`Audio player for ${recording.original_name}`}>
    <div className="recording-audio-heading"><div className="recording-audio-title"><Volume2 size={14} /><span>RECORDING AUDIO</span></div><label className="audio-rate-picker">Speed<select aria-label="Playback speed" value={rate} onChange={(event) => setRate(clampPlaybackRate(Number(event.target.value)))}>{playbackRates.map((value) => <option key={value} value={value}>{value}×</option>)}</select></label></div>
    <div className="audio-waveform-wrap">
      {waveform ? <canvas ref={canvasRef} className="audio-waveform" role="slider" tabIndex={0} aria-label="Seek through recording waveform" aria-valuemin={0} aria-valuemax={Math.round(duration)} aria-valuenow={Math.round(currentTime)} onPointerDown={onWaveformPointer} onPointerMove={(event) => { if (event.buttons === 1) onWaveformPointer(event); }} onKeyDown={(event) => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); seek(seekTarget(currentTime, event.key === "ArrowLeft" ? -5 : 5, duration)); } if (event.key === "Home") seek(0); if (event.key === "End") seek(duration); }} />
        : <div className="audio-waveform-placeholder">{waveformError ? "Waveform unavailable" : <LoaderCircle className="spin" size={15} />}</div>}
    </div>
    <div className="audio-time-row"><span>{formatDuration(currentTime)}</span><span>{formatDuration(duration || null)}</span></div>
    <audio ref={audioRef} key={`${recording.id}:${sourceMode}`} src={sourceUrl} preload="metadata" onLoadedMetadata={(event) => { setMediaDuration(Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : recording.duration_seconds ?? 0); setConverting(false); }} onTimeUpdate={(event) => { const time = event.currentTarget.currentTime; setCurrentTime(time); window.dispatchEvent(new CustomEvent("journal:audio-time", { detail: { recordingId: recording.id, time } })); }} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} onError={handleAudioError} />
    <div className="audio-controls"><button className="audio-transport" aria-label="Rewind 5 seconds" title="Rewind 5 seconds" onClick={() => seek(seekTarget(currentTime, -5, duration))}><Rewind size={13} /><small>5s</small></button><button className="audio-play-button" aria-label={playing ? "Pause recording" : "Play recording"} onClick={() => void togglePlayback()}>{playing ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" />}</button><button className="audio-transport" aria-label="Forward 5 seconds" title="Forward 5 seconds" onClick={() => seek(seekTarget(currentTime, 5, duration))}><FastForward size={13} /><small>5s</small></button><span className="audio-controls-spacer" />{converting && <span className="audio-converting"><LoaderCircle size={12} className="spin" /> Preparing audio…</span>}</div>
    {(sourceError || waveformError) && <div className="audio-player-message" role="status">{sourceError || waveformError}</div>}
    <div className="audio-waveform-note">Waveform shows audio level and pauses; it does not identify speech.</div>
  </section>;
}
