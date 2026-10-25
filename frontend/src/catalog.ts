/** Pure catalog formatting and filtering helpers, separated for simple testing. */
import type { Recording, TimedTranscriptWord } from "./types";

export type DurationFilter = "all" | "under10" | "10to40" | "over40";
export type SortKey = "original_name" | "duration_seconds" | "media_date" | "status";

const CONFIDENCE_STOPS = [
  { score: 0.25, color: [239, 68, 68] },
  { score: 0.50, color: [249, 115, 22] },
  { score: 0.75, color: [163, 230, 53] },
  { score: 1.00, color: [34, 197, 94] },
] as const;

/** Map Whisper's 0–1 probability to the requested red-to-green confidence scale. */
export function confidenceColor(probability: number | null | undefined): string | null {
  if (probability === null || probability === undefined || !Number.isFinite(probability)) return null;
  const score = Math.max(0, Math.min(1, probability));
  if (score <= CONFIDENCE_STOPS[0].score) return "#ef4444";
  const upperIndex = CONFIDENCE_STOPS.findIndex((stop) => score <= stop.score);
  if (upperIndex < 1) return "#22c55e";
  const lower = CONFIDENCE_STOPS[upperIndex - 1];
  const upper = CONFIDENCE_STOPS[upperIndex];
  const portion = (score - lower.score) / (upper.score - lower.score);
  const channels = lower.color.map((channel, index) => Math.round(channel + (upper.color[index] - channel) * portion));
  return `#${channels.map((channel) => channel.toString(16).padStart(2, "0")).join("")}`;
}

/** Avoid coloring text when word timings cannot reconstruct the exact transcript. */
export function alignmentMatchesTranscript(text: string, words: TimedTranscriptWord[]): boolean {
  return words.length > 0 && words.map((word) => word.text).join("").trim() === text.trim();
}

/** Check whether every currently listed text block is collapsed. */
export function areAllBlocksCollapsed(blockIds: string[], collapsedIds: ReadonlySet<string>): boolean {
  return blockIds.length > 0 && blockIds.every((id) => collapsedIds.has(id));
}

/** Count whitespace-separated words for output metadata without changing stored text. */
export function countWords(text: string): number {
  const trimmed = text.trim();
  return trimmed ? trimmed.split(/\s+/u).length : 0;
}

/** Show whole seconds and all non-zero units so even short clips are explicit. */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "—";
  let remaining = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(remaining / 3600);
  remaining %= 3600;
  const minutes = Math.floor(remaining / 60);
  const secs = remaining % 60;
  const parts = [hours ? `${hours}h` : "", minutes ? `${minutes}m` : "", secs || (!hours && !minutes) ? `${secs}s` : ""].filter(Boolean);
  return parts.join(" ");
}

/** Clamp player seeks to the recording so keyboard, buttons, and waveform share behavior. */
export function seekTarget(currentSeconds: number, offsetSeconds: number, durationSeconds: number): number {
  return Math.max(0, Math.min(Math.max(0, durationSeconds), currentSeconds + offsetSeconds));
}

/** Keep playback rate within the supported app range even if a control receives invalid input. */
export function clampPlaybackRate(rate: number): number {
  return Math.max(0.5, Math.min(2, Number.isFinite(rate) ? rate : 1));
}

/** Display embedded recording metadata without substituting the later import date. */
export function formatDate(value: string | null): string {
  if (!value) return "Unknown date";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date);
}

/** Apply status and duration filters before sorting the visible rows. */
export function filterAndSort(
  rows: Recording[],
  status: "all" | "untranscribed" | "transcribed",
  duration: DurationFilter,
  query: string,
  key: SortKey,
  direction: "asc" | "desc",
): Recording[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  return rows
    .filter((row) => status === "all" || row.status === status)
    .filter((row) => {
      const minutes = row.duration_seconds === null ? null : row.duration_seconds / 60;
      if (duration === "under10") return minutes !== null && minutes < 10;
      if (duration === "10to40") return minutes !== null && minutes >= 10 && minutes <= 40;
      if (duration === "over40") return minutes !== null && minutes > 40;
      return true;
    })
    .filter((row) => !normalizedQuery || row.original_name.toLocaleLowerCase().includes(normalizedQuery))
    .sort((left, right) => {
      const a = left[key];
      const b = right[key];
      const result = key === "duration_seconds"
        ? (a as number | null ?? -1) - (b as number | null ?? -1)
        : String(a ?? "").localeCompare(String(b ?? ""));
      return direction === "asc" ? result : -result;
    });
}
