"use client";

import { use, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { audioUrl, getJobStatus } from "@/lib/api";
import { transposeKeyLabel, transposeProgression } from "@/lib/transpose";
import ChordTimeline from "@/components/ChordTimeline";
import TransposeControl from "@/components/TransposeControl";
import AudioPlayer from "@/components/AudioPlayer";

function activeChordIndex(
  chords: Array<{ timestamp: number; end?: number }>,
  time: number
): number | null {
  if (!chords.length) return null;
  for (let i = 0; i < chords.length; i++) {
    const start = chords[i].timestamp;
    const end =
      chords[i].end ??
      (i + 1 < chords.length ? chords[i + 1].timestamp : start + 999);
    if (time >= start && time < end) return i;
  }
  // after last chord start
  if (time >= chords[chords.length - 1].timestamp) return chords.length - 1;
  return null;
}

function formatProgression(
  chords: Array<{ timestamp: number; chord: string }>
): string {
  return chords
    .map((c) => {
      const m = Math.floor(c.timestamp / 60);
      const s = Math.floor(c.timestamp % 60)
        .toString()
        .padStart(2, "0");
      return `[${m}:${s}] ${c.chord}`;
    })
    .join("\n");
}

export default function ResultsPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = use(params);
  const [semitones, setSemitones] = useState(0);
  const [playhead, setPlayhead] = useState(0);
  const [seekTo, setSeekTo] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);

  const { data, error } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => getJobStatus(jobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "done" || status === "failed") return false;
      return 2000;
    },
    retry: (failureCount) => failureCount < 5,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10_000),
  });

  const transposedChords = useMemo(
    () =>
      data?.result?.chords
        ? transposeProgression(data.result.chords, semitones)
        : [],
    [data?.result?.chords, semitones]
  );

  const originalKey = data?.result?.key;
  const transposedKey = originalKey
    ? transposeKeyLabel(originalKey, semitones)
    : undefined;

  const activeIndex = activeChordIndex(transposedChords, playhead);
  const isLoading =
    !data || data.status === "queued" || data.status === "processing";

  const handleCopy = async () => {
    const text = formatProgression(transposedChords);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  };

  return (
    <main className="min-h-screen bg-gray-950 p-6">
      <div className="max-w-4xl mx-auto">
        <div className="mb-8">
          <Link
            href="/"
            className="text-gray-500 hover:text-gray-300 text-sm transition-colors"
          >
            ← Upload new song
          </Link>
          <h1 className="text-3xl font-bold text-white mt-3 tracking-tight">
            Chord Analysis
          </h1>
        </div>

        {isLoading && (
          <div className="flex flex-col items-center justify-center py-28 gap-6">
            <div className="w-12 h-12 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
            <div className="text-center">
              <p className="text-white text-lg font-medium">
                {data?.status === "processing"
                  ? "Analyzing chords…"
                  : "Queued for analysis…"}
              </p>
              <p className="text-gray-500 text-sm mt-1 max-w-sm">
                {!data
                  ? "Server may be waking up — first request can take up to 60 s"
                  : "Audio analysis usually completes in 10–40 seconds"}
              </p>
            </div>
          </div>
        )}

        {(error || data?.status === "failed") && (
          <div className="p-6 bg-red-900/40 border border-red-700 rounded-xl text-red-300">
            <p className="font-semibold mb-1">Analysis failed</p>
            <p className="text-sm">
              {data?.error ??
                (error instanceof Error
                  ? error.message
                  : "An unknown error occurred.")}
            </p>
          </div>
        )}

        {data?.status === "done" && data.result && (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-4 text-sm text-gray-400">
              <span>
                🎸 {data.result.chords.length} chord changes
              </span>
              <span>♩ {data.result.tempo} BPM</span>
              {data.result.key && (
                <span>
                  🔑 {semitones === 0 ? data.result.key : transposedKey}
                </span>
              )}
              {data.result.duration != null && (
                <span>
                  ⏱ {Math.floor(data.result.duration / 60)}:
                  {Math.floor(data.result.duration % 60)
                    .toString()
                    .padStart(2, "0")}
                </span>
              )}
              {data.result.engine && (
                <span className="text-gray-600">via {data.result.engine}</span>
              )}
            </div>

            <AudioPlayer
              src={audioUrl(jobId)}
              onTimeUpdate={setPlayhead}
              seekTo={seekTo}
            />

            <TransposeControl
              semitones={semitones}
              onChange={setSemitones}
              originalKey={originalKey}
              transposedKey={transposedKey}
            />

            <div className="flex justify-end">
              <button
                type="button"
                onClick={handleCopy}
                className="text-xs text-gray-400 hover:text-white border border-gray-700 hover:border-gray-500 rounded-lg px-3 py-1.5 transition-colors"
              >
                {copied ? "Copied!" : "Copy progression"}
              </button>
            </div>

            <ChordTimeline
              chords={transposedChords}
              activeIndex={activeIndex}
              onSelect={(_i, ts) => {
                setSeekTo(ts);
                // allow re-seeking same timestamp
                setTimeout(() => setSeekTo(null), 50);
              }}
            />

            <p className="text-xs text-gray-600 text-center pt-4">
              Automatic chord detection is best-effort — always trust your ear
              on complex / distorted tracks.
            </p>
          </div>
        )}
      </div>
    </main>
  );
}
