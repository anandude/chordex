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

export interface AnalysisResult {
  chords: ChordEvent[];
  tempo: number;
  key?: string;
  duration?: number;
  engine?: string;
  /** v2: word-level lyrics (added when lyrics transcription is enabled) */
  lyrics?: Array<{ timestamp: number; word: string }>;
}

export interface JobStatus {
  status: "queued" | "processing" | "done" | "failed";
  result: AnalysisResult | null;
  error: string | null;
}

export function audioUrl(jobId: string): string {
  return `${API_URL}/api/audio/${encodeURIComponent(jobId)}`;
}

export async function uploadAudio(file: File): Promise<{ job_id: string }> {
  const formData = new FormData();
  formData.append("file", file);

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

export async function getJobStatus(jobId: string): Promise<JobStatus> {
  const res = await fetch(`${API_URL}/api/status/${encodeURIComponent(jobId)}`);
  if (!res.ok) {
    if (res.status === 404) throw new Error("Job not found");
    throw new Error("Failed to fetch job status");
  }
  return res.json();
}
