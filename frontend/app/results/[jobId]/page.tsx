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

// Stage ids published by the worker (progress:{job_id}) → readable labels. The
// model stages matter: a first run in a new language downloads ~1 GB, which
// used to look like a hang.
const STAGE_LABELS: Record<string, string> = {
  chords: "detecting chords",
  fetching_lyrics: "looking for existing lyrics",
  separating: "isolating the vocals",
  downloading_model: "downloading the speech model (first run only)",
  loading_model: "loading the speech model",
  transcribing: "transcribing the vocals",
  aligning: "aligning words to the audio",
  cleaning: "cleaning up the lyrics",
  done: "wrapping up",
};

function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage.replace(/_/g, " ");
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
    <span className="inline-flex items-center gap-2.5 bg-coal border-2 border-black shadow-hard-sm px-3 py-2">
      <Image src={icon} alt="" width={20} height={20} className="w-5 h-5" />
      <span className="font-cl text-paper-dim text-xs uppercase tracking-wider">
        {label}
      </span>
      <span className="font-pixel text-paper text-base">{value}</span>
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
      if (status === "failed") return false;
      // S3: chords resolve first — keep polling in the background until the
      // slow lyrics job also settles, then go quiet.
      const lyrics = query.state.data?.result?.lyrics_status;
      if (status === "done" && lyrics !== "pending" && lyrics !== "processing")
        return false;
      return 2000;
    },
    retry: (failureCount) => failureCount < 5,
    retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10_000),
  });

  const isLoading =
    !data || data.status === "queued" || data.status === "processing";
  const failed = Boolean(error) || data?.status === "failed";
  const progressPct =
    typeof data?.progress === "number"
      ? Math.round(Math.min(Math.max(data.progress, 0), 1) * 100)
      : null;

  useEffect(() => {
    if (!isLoading) return;
    const t = setInterval(
      () => setStatusLine((i) => (i + 1) % PROCESSING_LINES.length),
      2600
    );
    return () => clearInterval(t);
  }, [isLoading]);

  // hoisted from the response so the memo deps stay exact
  const resultChords = data?.result?.chords;
  const resultKey = data?.result?.key;

  // 1) optional user transpose on original chords
  const transposedOriginal = useMemo(
    () =>
      resultChords ? transposeProgression(resultChords, semitones) : [],
    [resultChords, semitones]
  );

  // 2) easy mode from transposed
  const easy = useMemo(() => {
    if (!transposedOriginal.length) return null;
    const key = resultKey
      ? transposeKeyLabel(resultKey, semitones)
      : undefined;
    return applyEasyMode(transposedOriginal, key);
  }, [transposedOriginal, resultKey, semitones]);

  const displayChords = easyMode && easy ? easy.chords : transposedOriginal;

  const originalKey = resultKey;
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
            className="inline-flex items-center gap-2.5 min-h-11 bg-coal border-2 border-black shadow-hard-sm px-3.5 py-2 font-cl text-paper text-sm hover:-translate-y-0.5 hover:text-paper transition-transform"
          >
            <Image
              src="/icons/upload.svg"
              alt=""
              width={20}
              height={20}
              className="w-5 h-5"
            />
            new song
          </Link>
          <Image
            src="/logo.webp"
            alt="ChordLens"
            width={140}
            height={93}
            className="w-28 sm:w-36 h-auto"
          />
        </header>

        {/* Processing state */}
        {isLoading && !failed && (
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
            <div className="text-center w-full max-w-md">
              <p className="font-pixel text-paper text-xl sm:text-2xl tracking-wide">
                {data?.status === "processing" ? "ANALYZING…" : "QUEUED…"}
              </p>
              <p className="font-cl text-paper-dim text-sm sm:text-base mt-2.5 animate-blink">
                {data?.stage
                  ? stageLabel(data.stage) + "…"
                  : PROCESSING_LINES[statusLine]}
              </p>

              {progressPct !== null && (
                <div className="mt-5">
                  <div
                    className="h-3 bg-soot border-2 border-black"
                    role="progressbar"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={progressPct}
                  >
                    <div
                      className="h-full bg-mint transition-[width] duration-700"
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                  <p className="font-pixel text-paper-dim text-xs mt-2.5">
                    {progressPct}%
                  </p>
                </div>
              )}

              <p className="font-cl text-paper-dim/80 text-xs sm:text-sm mt-5">
                {data?.stage === "downloading_model"
                  ? "one-off download · later songs in this language start instantly"
                  : "chords land in seconds · lyrics follow when ready (1–3 min with the small model, longer on a first-run language download)"}
              </p>
            </div>
          </div>
        )}

        {/* Failure state */}
        {failed && (
          <div
            role="alert"
            className="p-5 sm:p-6 bg-tomato border-2 border-black shadow-hard text-ink"
          >
            <p className="font-pixel text-lg sm:text-xl mb-2.5">
              ANALYSIS FAILED
            </p>
            <p className="font-cl text-sm sm:text-base font-semibold mb-4">
              {data?.error ??
                (error instanceof Error
                  ? error.message
                  : "An unknown error occurred.")}
            </p>
            <Link
              href="/"
              className="inline-flex items-center gap-2 min-h-11 bg-ink text-paper border-2 border-black shadow-hard-sm px-3.5 py-2 font-pixel text-xs hover:-translate-y-0.5 transition-transform"
            >
              TRY ANOTHER FILE
            </Link>
          </div>
        )}

        {/* Results */}
        {data?.status === "done" && result && (
          <div className="space-y-4 sm:space-y-5">
            {/* Stats */}
            <div className="flex flex-wrap items-center gap-2.5">
              <StatChip
                icon="/icons/note.svg"
                label="chords"
                value={`${result.chords.length}`}
              />
              <StatChip
                icon="/icons/speed.svg"
                label="bpm"
                value={
                  result.tempo != null && result.tempo > 0
                    ? `${Math.round(result.tempo)}`
                    : "—"
                }
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
                <span className="inline-flex items-center min-h-9 bg-lime border-2 border-black shadow-hard-sm px-3 py-2">
                  <span className="font-cl text-ink text-xs uppercase tracking-wider">
                    verified lyrics
                  </span>
                </span>
              )}
              {result.lyrics_source === "asr" &&
                result.lyric_lines &&
                result.lyric_lines.length > 0 && (
                  <span className="font-cl text-paper-dim text-xs sm:text-sm self-center">
                    machine-transcribed — may have errors
                  </span>
                )}
              {result.engine && (
                <span className="font-cl text-paper-dim text-xs sm:text-sm self-center">
                  via {result.engine}
                </span>
              )}
              {/* S3: chords render first; lyrics stream in behind. */}
              {(result.lyrics_status === "pending" ||
                result.lyrics_status === "processing") && (
                <span className="font-cl text-paper-dim text-xs sm:text-sm self-center animate-blink">
                  lyrics still cooking
                  {data?.stage ? ` — ${stageLabel(data.stage)}…` : "…"}
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
            <div className="bg-coal border-2 border-black shadow-hard p-3 sm:p-4">
              <div className="flex flex-wrap items-stretch gap-3 sm:gap-4">
                <div className="flex-1 min-w-[16rem] bg-ink/45 border-2 border-soot px-3.5 py-3">
                  <TransposeControl
                    semitones={semitones}
                    onChange={setSemitones}
                    originalKey={originalKey}
                    transposedKey={transposedKey}
                  />
                </div>
                <div className="flex-1 min-w-[16rem] bg-ink/45 border-2 border-soot px-3.5 py-3">
                  <EasyModeControl
                    enabled={easyMode}
                    onChange={setEasyMode}
                    capo={easy?.capo ?? result.easy?.capo ?? 0}
                    reason={easy?.reason ?? result.easy?.reason}
                    easyKey={easy?.easyKey ?? result.easy?.easy_key ?? undefined}
                  />
                </div>
                <button
                  type="button"
                  onClick={handleCopy}
                  className="self-center w-full sm:w-auto min-h-11 inline-flex items-center justify-center gap-2 font-pixel text-xs sm:text-sm px-5 py-2.5 bg-paper text-ink border-2 border-black shadow-hard-sm hover:-translate-y-px active:translate-x-[2px] active:translate-y-[2px] active:shadow-none transition-transform"
                >
                  <Image
                    src="/icons/copy.svg"
                    alt=""
                    width={16}
                    height={16}
                    className="w-4 h-4"
                  />
                  {copied ? "COPIED!" : "COPY"}
                </button>
              </div>
            </div>

            {/* The sheet */}
            {result.lyric_lines_roman &&
              result.lyric_lines_roman.length > 0 && (
                <div className="flex flex-wrap items-center gap-2.5 sm:gap-3">
                  <span className="font-cl text-paper-dim text-xs uppercase tracking-[0.2em]">
                    Script
                  </span>
                  <div
                    role="group"
                    aria-label="Lyrics script"
                    className="inline-flex border-2 border-black shadow-hard-sm"
                  >
                    {(["native", "roman", "both"] as const).map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => setScript(s)}
                        aria-pressed={script === s}
                        className={`min-h-9 px-3.5 py-2 font-pixel text-xs sm:text-sm border-r-2 border-black last:border-r-0 transition-colors ${
                          script === s
                            ? "bg-gold text-ink"
                            : "bg-coal text-paper-dim hover:text-paper"
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

            <p className="font-cl text-paper-dim text-xs sm:text-sm text-center pt-1 pb-2">
              auto-generated — always trust your ear on complex tracks
            </p>
          </div>
        )}
      </div>
    </main>
  );
}
