"use client";

import { use, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import Image from "next/image";
import { audioUrl, getJobStatus } from "@/lib/api";
import { transposeKeyLabel, transposeProgression } from "@/lib/transpose";
import { applyEasyMode } from "@/lib/easyChords";
import { activeChordIndex } from "@/lib/chordSheet";
import AudioPlayer from "@/components/AudioPlayer";
import NowNextBar from "@/components/NowNextBar";
import ChordSheet from "@/components/ChordSheet";
import TransposeControl from "@/components/TransposeControl";
import EasyModeControl from "@/components/EasyModeControl";

const PROCESSING_LINES = [
  "separating vocals from the mix…",
  "listening for chord changes…",
  "estimating key & tempo…",
  "transcribing lyrics…",
  "snapping chords to the beat…",
  "looking for easy shapes…",
  "almost there…",
];

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

function StatChip({
  icon,
  label,
  value,
}: {
  icon: string;
  label: string;
  value: string;
}) {
  return (
    <span className="inline-flex items-center gap-2 bg-coal border-2 border-black shadow-hard-sm px-2.5 py-1.5">
      <Image src={icon} alt="" width={18} height={18} className="w-[18px] h-[18px]" />
      <span className="font-cl text-paper-dim text-xs uppercase tracking-wider">
        {label}
      </span>
      <span className="font-pixel text-paper text-sm">{value}</span>
    </span>
  );
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
  const [playing, setPlaying] = useState(false);
  const [seekTo, setSeekTo] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const [statusLine, setStatusLine] = useState(0);
  const [script, setScript] = useState<"native" | "roman" | "both">("native");

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

  const isLoading =
    !data || data.status === "queued" || data.status === "processing";

  useEffect(() => {
    if (!isLoading) return;
    const t = setInterval(
      () => setStatusLine((i) => (i + 1) % PROCESSING_LINES.length),
      2600
    );
    return () => clearInterval(t);
  }, [isLoading]);

  // 1) optional user transpose on original chords
  const transposedOriginal = useMemo(
    () =>
      data?.result?.chords
        ? transposeProgression(data.result.chords, semitones)
        : [],
    [data?.result?.chords, semitones]
  );

  // 2) easy mode from transposed
  const easy = useMemo(() => {
    if (!transposedOriginal.length) return null;
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

  const handleCopy = async () => {
    const text = formatProgression(displayChords, {
      easy: easyMode,
      capo: easy?.capo,
    });
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

  const result = data?.result;
  const durationLabel =
    result?.duration != null
      ? `${Math.floor(result.duration / 60)}:${Math.floor(result.duration % 60)
          .toString()
          .padStart(2, "0")}`
      : "?";

  return (
    <main className="min-h-screen p-4 sm:p-6">
      <div className="max-w-3xl mx-auto pb-16">
        {/* Header */}
        <header className="flex items-center justify-between gap-4 mb-5">
          <Link
            href="/"
            className="inline-flex items-center gap-2 font-cl text-paper-dim text-sm hover:text-paper transition-colors"
          >
            <Image
              src="/icons/upload.svg"
              alt=""
              width={18}
              height={18}
              className="w-[18px] h-[18px]"
            />
            new song
          </Link>
          <Image
            src="/logo.webp"
            alt="ChordLens"
            width={140}
            height={93}
            className="w-28 sm:w-32 h-auto"
          />
        </header>

        {/* Processing state */}
        {isLoading && (
          <div className="flex flex-col items-center justify-center py-24 gap-7 animate-pop">
            <div className="flex items-end gap-2 h-16" aria-hidden>
              {[0, 1, 2, 3, 4, 5, 6].map((i) => (
                <span
                  key={i}
                  className="w-3 bg-paper border-2 border-black animate-eq origin-bottom"
                  style={{
                    height: "100%",
                    animationDelay: `${i * 0.14}s`,
                  }}
                />
              ))}
            </div>
            <div className="text-center">
              <p className="font-pixel text-paper text-xl sm:text-2xl tracking-wide">
                {data?.status === "processing" ? "ANALYZING…" : "QUEUED…"}
              </p>
              <p className="font-cl text-paper-dim text-sm mt-2 animate-blink">
                {data?.stage
                  ? data.stage.replace(/_/g, " ") + "…"
                  : PROCESSING_LINES[statusLine]}
              </p>
              <p className="font-cl text-paper-dim/80 text-xs mt-4 max-w-sm mx-auto">
                chords land in ~20–90 s · lyrics with the small model take
                1–3 min (Malayalam uses a bigger model and can take longer on
                first run)
              </p>
            </div>
          </div>
        )}

        {/* Failure state */}
        {(error || data?.status === "failed") && (
          <div
            role="alert"
            className="p-6 bg-tomato border-2 border-black shadow-hard text-ink"
          >
            <p className="font-pixel text-lg mb-2">ANALYSIS FAILED</p>
            <p className="font-cl text-sm font-semibold">
              {data?.error ??
                (error instanceof Error
                  ? error.message
                  : "An unknown error occurred.")}
            </p>
          </div>
        )}

        {/* Results */}
        {data?.status === "done" && result && (
          <div className="space-y-4">
            {/* Stats */}
            <div className="flex flex-wrap items-center gap-2">
              <StatChip
                icon="/icons/note.svg"
                label="chords"
                value={`${result.chords.length}`}
              />
              <StatChip
                icon="/icons/speed.svg"
                label="bpm"
                value={`${Math.round(result.tempo) || "—"}`}
              />
              <StatChip
                icon="/icons/timer.svg"
                label="len"
                value={durationLabel}
              />
              {result.lyrics_language && (
                <StatChip
                  icon="/icons/mic.svg"
                  label="vox"
                  value={result.lyrics_language}
                />
              )}
              {result.lyrics_source && result.lyrics_source !== "asr" && (
                <span className="inline-flex items-center gap-2 bg-lime border-2 border-black shadow-hard-sm px-2.5 py-1.5">
                  <span className="font-cl text-ink text-xs uppercase tracking-wider">
                    verified lyrics
                  </span>
                </span>
              )}
              {result.lyrics_source === "asr" &&
                result.lyric_lines &&
                result.lyric_lines.length > 0 && (
                  <span className="font-cl text-paper-dim/75 text-[11px] self-center">
                    machine-transcribed — may have errors
                  </span>
                )}
              {result.engine && (
                <span className="font-cl text-paper-dim/75 text-[11px] self-center">
                  via {result.engine}
                </span>
              )}
            </div>

            <AudioPlayer
              src={audioUrl(jobId)}
              chords={displayChords}
              onTimeUpdate={setPlayhead}
              onPlayingChange={setPlaying}
              seekTo={seekTo}
            />

            <NowNextBar
              chords={displayChords}
              activeIndex={activeIndex}
              currentTime={playhead}
              playing={playing}
              onSeek={seek}
            />

            {/* Toolbar: transpose + easy + copy */}
            <div className="bg-coal border-2 border-black shadow-hard px-4 py-3 flex flex-wrap items-center gap-x-6 gap-y-3">
              <TransposeControl
                semitones={semitones}
                onChange={setSemitones}
                originalKey={originalKey}
                transposedKey={transposedKey}
              />
              <EasyModeControl
                enabled={easyMode}
                onChange={setEasyMode}
                capo={easy?.capo ?? result.easy?.capo ?? 0}
                reason={easy?.reason ?? result.easy?.reason}
                easyKey={
                  easy?.easyKey ?? result.easy?.easy_key ?? undefined
                }
              />
              <button
                type="button"
                onClick={handleCopy}
                className="ml-auto inline-flex items-center gap-2 font-pixel text-xs px-3 py-2 bg-paper text-ink border-2 border-black shadow-hard-sm hover:-translate-y-px active:translate-x-[2px] active:translate-y-[2px] active:shadow-none transition-transform"
              >
                <Image
                  src="/icons/copy.svg"
                  alt=""
                  width={14}
                  height={14}
                  className="w-3.5 h-3.5"
                />
                {copied ? "COPIED!" : "COPY"}
              </button>
            </div>

            {/* The sheet */}
            {result.lyric_lines_roman &&
              result.lyric_lines_roman.length > 0 && (
                <div className="flex items-center gap-2">
                  {(["native", "roman", "both"] as const).map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setScript(s)}
                      aria-pressed={script === s}
                      className={`font-pixel text-xs px-3 py-1.5 border-2 border-black transition-transform ${
                        script === s
                          ? "bg-gold text-ink shadow-hard-sm"
                          : "bg-coal text-paper-dim hover:-translate-y-px"
                      }`}
                    >
                      {s === "native"
                        ? "മലയാളം / हिंदी"
                        : s === "roman"
                          ? "ROMAN"
                          : "BOTH"}
                    </button>
                  ))}
                </div>
              )}
            <ChordSheet
              chords={displayChords}
              words={result.lyrics}
              lines={result.lyric_lines}
              romanLines={result.lyric_lines_roman}
              script={script}
              currentTime={playhead}
              activeChord={activeIndex}
              lyricsError={result.lyrics_error}
              onSeek={seek}
            />

            <p className="font-cl text-paper-dim/75 text-xs text-center pt-2">
              auto-generated — always trust your ear on complex tracks
            </p>
          </div>
        )}
      </div>
    </main>
  );
}
