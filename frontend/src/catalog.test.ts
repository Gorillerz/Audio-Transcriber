/** Tests for catalog formatting and filter/sort behavior. */
import { describe, expect, it } from "vitest";
import { alignmentMatchesTranscript, areAllBlocksCollapsed, clampPlaybackRate, confidenceColor, countWords, filterAndSort, formatDate, formatDuration, seekTarget } from "./catalog";
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

  it("clamps seeks to the start and end of audio", () => {
    expect(seekTarget(2, -5, 20)).toBe(0);
    expect(seekTarget(18, 5, 20)).toBe(20);
    expect(seekTarget(10, -5, 20)).toBe(5);
  });

  it("limits audio speed to the player range", () => {
    expect(clampPlaybackRate(1.5)).toBe(1.5);
    expect(clampPlaybackRate(5)).toBe(2);
    expect(clampPlaybackRate(0.1)).toBe(0.5);
    expect(clampPlaybackRate(Number.NaN)).toBe(1);
  });

  it("counts words in output text and treats whitespace-only text as empty", () => {
    expect(countWords("  Bonjour,   how are you?\nI'm well. ")).toBe(6);
    expect(countWords(" \n\t ")).toBe(0);
  });

  it("uses the requested confidence colors and interpolates between their anchors", () => {
    expect(confidenceColor(0.25)).toBe("#ef4444");
    expect(confidenceColor(0.5)).toBe("#f97316");
    expect(confidenceColor(0.75)).toBe("#a3e635");
    expect(confidenceColor(1)).toBe("#22c55e");
    expect(confidenceColor(0.1)).toBe("#ef4444");
    expect(confidenceColor(null)).toBeNull();
  });

  it("only applies word alignment when its exact text reconstructs the transcript", () => {
    const words = [
      { start: 0, end: 0.2, text: " Bonjour" },
      { start: 0.2, end: 0.4, text: "!" },
    ];
    expect(alignmentMatchesTranscript("Bonjour!", words)).toBe(true);
    expect(alignmentMatchesTranscript("Bonjour?", words)).toBe(false);
    expect(alignmentMatchesTranscript("", [])).toBe(false);
  });

  it("reports when all output text blocks are collapsed", () => {
    expect(areAllBlocksCollapsed(["one", "two"], new Set(["one", "two"]))).toBe(true);
    expect(areAllBlocksCollapsed(["one", "two"], new Set(["one"]))).toBe(false);
    expect(areAllBlocksCollapsed([], new Set())).toBe(false);
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
