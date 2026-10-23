/** Tests for catalog formatting and filter/sort behavior. */
import { describe, expect, it } from "vitest";
import { filterAndSort, formatDate, formatDuration } from "./catalog";
import type { Recording } from "./types";

const base = (id: string, name: string, seconds: number | null, status: Recording["status"]): Recording => ({
  id, original_name: name, stored_path: "", sha256: id, size_bytes: 12,
  duration_seconds: seconds, media_date: null, imported_at: "2026-10-01T10:00:00Z",
  mime_type: "audio/wav", extension: ".wav", status, status_source: "derived", possible_match_id: null, alias_count: 0, group_ids: [],
});

describe("catalog helpers", () => {
  it("formats missing and long durations", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(1)).toBe("1s");
    expect(formatDuration(90 * 60 + 4)).toBe("1h 30m 4s");
  });

  it("does not present the import date as a recording date", () => {
    expect(formatDate(null)).toBe("Unknown date");
  });

  it("combines status and duration filters and sorts by name", () => {
    const rows = [base("1", "long.wav", 2500, "untranscribed"), base("2", "short.wav", 300, "untranscribed"), base("3", "done.wav", 300, "transcribed")];
    const result = filterAndSort(rows, "untranscribed", "under10", "", "original_name", "asc");
    expect(result.map((row) => row.original_name)).toEqual(["short.wav"]);
    expect(filterAndSort(rows, "all", "over40", "", "duration_seconds", "desc").map((row) => row.id)).toEqual(["1"]);
  });

  it("sorts by embedded recording date and numeric duration", () => {
    const older = { ...base("1", "older.wav", 120, "untranscribed"), media_date: "2025-01-01" };
    const newer = { ...base("2", "newer.wav", 900, "transcribed"), media_date: "2026-01-01" };
    expect(filterAndSort([newer, older], "all", "all", "", "media_date", "asc").map((row) => row.id)).toEqual(["1", "2"]);
    expect(filterAndSort([older, newer], "all", "all", "", "duration_seconds", "asc").map((row) => row.id)).toEqual(["1", "2"]);
  });
});
