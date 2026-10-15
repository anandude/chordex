/**
 * api.ts
 * ------
 * Typed wrappers for the ChordLens backend API.
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface ChordEvent {
  timestamp: number;
  end?: number;
  chord: string;
  confidence?: number;
}

export interface LyricWord {
  timestamp: number;
  end?: number;
  word: string;
}

export interface LyricLine {
  timestamp: number;
  end?: number;
  text: string;
}

// ── Chord sheet (built by the backend: backend/pipeline/sheet.py) ──────────
// Chords are referenced by index into `chords`, so transpose / Easy Mode
// relabel without moving anything.

export interface SheetSeg {
  chord: number | null;
  text: string;
}

export interface SheetWord {
  text: string;
  t: number;
  end: number;
  segs: SheetSeg[];
  roman?: string;
}

export type SheetRow =
  | { kind: "section"; t: number; label: string }
  | { kind: "bars"; t: number; end: number; chords: number[]; beats: number[] }
  | {
      kind: "line";
      t: number;
      end: number;
      carry: number | null;
      chorus: boolean;
      words: SheetWord[];
      gaps: { after_word: number; chords: number[] }[];
    };

export interface Sheet {
  version: number;
  beat: number;
  rows: SheetRow[];
}

export interface EasyModeResult {
  capo: number;
  score: number;
  easy_key?: string | null;
  reason?: string;
  chords: ChordEvent[];
}

export interface AnalysisResult {
  chords: ChordEvent[];
  // Null (beat tracking skipped) or 0 (no beats found, e.g. drones or
  // pure-tone fixtures) — UI renders "—" for both.
  tempo: number | null;
  key?: string;
  duration?: number;
  engine?: string;
  // S3 staged delivery: chords render as soon as they land; the frontend
  // keeps polling while lyrics are still pending/processing.
  lyrics_status?: "pending" | "processing" | "done" | "failed" | "disabled" | null;
  lyrics?: LyricWord[];
  lyric_lines?: LyricLine[];
  lyric_lines_roman?: LyricLine[];
  lyrics_language?: string | null;
  lyrics_language_prob?: number | null;
  lyrics_error?: string | null;
  lyrics_source?: "lrclib_synced" | "lrclib_plain" | "asr" | null;
  lyrics_cleaned?: boolean | null;
  easy?: EasyModeResult;
  beats?: number[];
  sheet?: Sheet;
  /** Upload filename stem or the YouTube video title. */
  source_name?: string | null;
}

export interface JobStatus {
  status: "queued" | "processing" | "done" | "failed" | "cancelled";
  result: AnalysisResult | null;
  error: string | null;
  stage?: string | null;
  progress?: number | null;
  queue_name?: string | null;
  queue_position?: number | null;
  queue_depth?: number | null;
}

export interface UploadMeta {
  title?: string;
  artist?: string;
  album?: string;
}

export function audioUrl(jobId: string): string {
  return `${API_URL}/api/audio/${encodeURIComponent(jobId)}`;
}

export async function uploadAudio(
  file: File,
  language?: string,
  meta?: UploadMeta
): Promise<{ job_id: string }> {
  const formData = new FormData();
  formData.append("file", file);
  if (language && language !== "auto") formData.append("language", language);
  // Phase 2: user-supplied title/artist dramatically raise LRCLIB hit rate.
  if (meta?.title) formData.append("title", meta.title);
  if (meta?.artist) formData.append("artist", meta.artist);
  if (meta?.album) formData.append("album", meta.album);

  const res = await fetch(`${API_URL}/api/analyze`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(
      typeof err.detail === "string" ? err.detail : "Upload failed"
    );
  }

  return res.json();
}

export async function analyzeUrl(
  url: string,
  language?: string,
  meta?: UploadMeta
): Promise<{ job_id: string }> {
  const res = await fetch(`${API_URL}/api/analyze-url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      url,
      language: language && language !== "auto" ? language : null,
      title: meta?.title || null,
      artist: meta?.artist || null,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Couldn't fetch that link" }));
    throw new Error(
      typeof err.detail === "string" ? err.detail : "Couldn't fetch that link"
    );
  }
  return res.json();
}

/** Mirrors backend/youtube.py's host allow-list. */
export function isYouTubeUrl(text: string): boolean {
  try {
    const u = new URL(text.trim());
    return (
      /^https?:$/.test(u.protocol) &&
      /^((www|m|music)\.)?youtube\.com$|^(www\.)?youtu\.be$/.test(u.hostname)
    );
  } catch {
    return false;
  }
}

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${API_URL}/api/status/${encodeURIComponent(jobId)}`);
  if (!res.ok) {
    if (res.status === 404) throw new Error("Job not found");
    throw new Error("Failed to fetch job status");
  }
  return res.json();
}

export async function cancelJob(jobId: string): Promise<void> {
  const res = await fetch(`${API_URL}/api/jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to cancel job");
}
