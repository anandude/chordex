"use client";

import { useEffect, useRef } from "react";
import type { LyricLine, LyricWord } from "@/lib/api";

interface Props {
  lines?: LyricLine[];
  words?: LyricWord[];
  currentTime: number;
  error?: string | null;
  onSeek?: (time: number) => void;
}

function activeLineIndex(lines: LyricLine[], time: number): number {
  if (!lines.length) return -1;
  for (let i = 0; i < lines.length; i++) {
    const start = lines[i].timestamp;
    const end =
      lines[i].end ??
      (i + 1 < lines.length ? lines[i + 1].timestamp : start + 10);
    if (time >= start && time < end) return i;
  }
  if (time >= lines[lines.length - 1].timestamp) return lines.length - 1;
  return -1;
}

export default function LyricsDisplay({
  lines = [],
  words = [],
  currentTime,
  error,
  onSeek,
}: Props) {
  const activeRef = useRef<HTMLButtonElement | null>(null);
  const active = activeLineIndex(lines, currentTime);

  useEffect(() => {
    activeRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
    });
  }, [active]);

  if (error && !lines.length && !words.length) {
    return (
      <section className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-widest mb-2">
          Lyrics
        </h2>
        <p className="text-sm text-gray-500">
          Lyrics unavailable: {error}
        </p>
      </section>
    );
  }

  if (!lines.length && !words.length) {
    return (
      <section className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-widest mb-2">
          Lyrics
        </h2>
        <p className="text-sm text-gray-500">No lyrics detected for this track.</p>
      </section>
    );
  }

  const displayLines =
    lines.length > 0
      ? lines
      : // fallback: chunk words into pseudo-lines every ~8 words
        (() => {
          const chunks: LyricLine[] = [];
          for (let i = 0; i < words.length; i += 8) {
            const slice = words.slice(i, i + 8);
            chunks.push({
              timestamp: slice[0].timestamp,
              end: slice[slice.length - 1].end ?? slice[slice.length - 1].timestamp,
              text: slice.map((w) => w.word).join(" "),
            });
          }
          return chunks;
        })();

  return (
    <section className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <h2 className="text-sm font-medium text-gray-500 uppercase tracking-widest mb-3">
        Lyrics
      </h2>
      <div className="max-h-72 overflow-y-auto space-y-1 pr-1">
        {displayLines.map((line, i) => {
          const isActive = i === active;
          return (
            <button
              key={`${line.timestamp}-${i}`}
              type="button"
              ref={isActive ? activeRef : undefined}
              onClick={() => onSeek?.(line.timestamp)}
              className={[
                "w-full text-left px-3 py-2 rounded-lg transition-colors text-sm leading-relaxed",
                isActive
                  ? "bg-amber-500/15 text-amber-100 border border-amber-500/30"
                  : "text-gray-400 hover:bg-gray-800/80 hover:text-gray-200 border border-transparent",
              ].join(" ")}
            >
              {line.text}
            </button>
          );
        })}
      </div>
      <p className="text-[11px] text-gray-600 mt-2">
        Auto-transcribed — may be imperfect. Click a line to seek.
      </p>
    </section>
  );
}
