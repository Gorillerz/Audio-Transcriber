/** Pure catalog formatting and filtering helpers, separated for simple testing. */
import type { Recording } from "./types";

export type DurationFilter = "all" | "under10" | "10to40" | "over40";
export type SortKey = "original_name" | "duration_seconds" | "media_date" | "status";

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
