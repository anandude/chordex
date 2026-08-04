"use client";

import { use, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { audioUrl, getJobStatus } from "@/lib/api";
import { transposeKeyLabel, transposeProgression } from "@/lib/transpose";
import { applyEasyMode } from "@/lib/easyChords";
import ChordTimeline from "@/components/ChordTimeline";
import TransposeControl from "@/components/TransposeControl";
import AudioPlayer from "@/components/AudioPlayer";
import LyricsDisplay from "@/components/LyricsDisplay";
import EasyModeControl from "@/components/EasyModeControl";

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
  if (time >= chords[chords.length - 1].timestamp) return chords.length - 1;
  return null;
}

function formatProgression(
  chords: Array<{ timestamp: number; chord: string }>,
  opts?: { capo?: number; easy?: boolean }
): string {
  const header: string[] = [];
  if (opts?.easy) {
    header.push(
      opts.capo && opts.capo > 0
        ? `Easy mode · Capo ${opts.capo}`
        : "Easy mode · No capo"
    );
  }
  const body = chords
    .map((c) => {
      const m = Math.floor(c.timestamp / 60);
      const s = Math.floor(c.timestamp % 60)
        .toString()
        .padStart(2, "0");
      return `[${m}:${s}] ${c.chord}`;
    })
    .join("\n");
  return header.length ? `${header.join("\n")}\n\n${body}` : body;
}

export default function ResultsPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = use(params);
  const [semitones, setSemitones] = useState(0);
  const [easyMode, setEasyMode] = useState(false);
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

  // 1) optional user transpose on original chords
  const transposedOriginal = useMemo(
    () =>
      data?.result?.chords
        ? transposeProgression(data.result.chords, semitones)
        : [],
    [data?.result?.chords, semitones]
  );

  // 2) easy mode from transposed (or server precompute when no transpose)
  const easy = useMemo(() => {
    if (!transposedOriginal.length) return null;
    // Prefer live client recompute so transpose + easy compose correctly
    const key = data?.result?.key
      ? transposeKeyLabel(data.result.key, semitones)
      : undefined;
    return applyEasyMode(transposedOriginal, key);
  }, [transposedOriginal, data?.result?.key, semitones]);

  const displayChords = easyMode && easy ? easy.chords : transposedOriginal;

  const originalKey = data?.result?.key;
  const transposedKey = originalKey
    ? transposeKeyLabel(originalKey, semitones)
    : undefined;

  const activeIndex = activeChordIndex(displayChords, playhead);
  const isLoading =
    !data || data.status === "queued" || data.status === "processing";

  const handleCopy = async () => {
    const text = formatProgression(displayChords, {
      easy: easyMode,
      capo: easy?.capo,
    });
    // Append lyrics lines if present
    const lines = data?.result?.lyric_lines;
    const full =
      lines && lines.length
        ? `${text}\n\n--- Lyrics ---\n${lines.map((l) => l.text).join("\n")}`
        : text;
    try {
      await navigator.clipboard.writeText(full);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  };

  const seek = (ts: number) => {
    setSeekTo(ts);
    setTimeout(() => setSeekTo(null), 50);
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
                  ? "Analyzing chords & lyrics…"
                  : "Queued for analysis…"}
              </p>
              <p className="text-gray-500 text-sm mt-1 max-w-sm">
                {!data
                  ? "Server may be waking up — first request can take up to 60 s"
                  : "Chords + lyrics usually finish in 20–90 seconds (first lyrics run downloads a small model)"}
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
              <span>🎸 {data.result.chords.length} chord changes</span>
              <span>♩ {data.result.tempo} BPM</span>
              {data.result.key && (
                <span>
                  🔑{" "}
                  {easyMode && easy?.easyKey
                    ? `${easy.easyKey} (shapes)`
                    : semitones === 0
                      ? data.result.key
                      : transposedKey}
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
              {data.result.lyrics_language && (
                <span className="text-gray-600">
                  lyrics: {data.result.lyrics_language}
                </span>
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

            <EasyModeControl
              enabled={easyMode}
              onChange={setEasyMode}
              capo={easy?.capo ?? data.result.easy?.capo ?? 0}
              reason={easy?.reason ?? data.result.easy?.reason}
              easyKey={easy?.easyKey ?? data.result.easy?.easy_key ?? undefined}
            />

            <div className="flex justify-end">
              <button
                type="button"
                onClick={handleCopy}
                className="text-xs text-gray-400 hover:text-white border border-gray-700 hover:border-gray-500 rounded-lg px-3 py-1.5 transition-colors"
              >
                {copied ? "Copied!" : "Copy chords + lyrics"}
              </button>
            </div>

            <ChordTimeline
              chords={displayChords}
              activeIndex={activeIndex}
              onSelect={(_i, ts) => seek(ts)}
            />

            <LyricsDisplay
              lines={data.result.lyric_lines}
              words={data.result.lyrics}
              currentTime={playhead}
              error={data.result.lyrics_error}
              onSeek={seek}
            />

            <p className="text-xs text-gray-600 text-center pt-4">
              Automatic chords & lyrics are best-effort — always trust your ear
              on complex tracks.
            </p>
          </div>
        )}
      </div>
    </main>
  );
}
