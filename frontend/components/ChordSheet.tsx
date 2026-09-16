"use client";

import { useEffect, useMemo, useRef } from "react";
import { ChordEvent, LyricLine, LyricWord } from "@/lib/api";
import { buildSheet, activeRowIndex } from "@/lib/chordSheet";
import { chordChipClass } from "@/lib/chordStyle";

interface Props {
  chords: ChordEvent[];
  words?: LyricWord[];
  lines?: LyricLine[];
  /** Phase 5b: romanised display lines (native script stays canonical). */
  romanLines?: LyricLine[];
  script?: "native" | "roman" | "both";
  currentTime: number;
  activeChord: number | null;
  lyricsError?: string | null;
  onSeek: (time: number) => void;
}

function romanFor(
  romanLines: LyricLine[] | undefined,
  timestamp: number
): string | null {
  if (!romanLines) return null;
  for (const l of romanLines) {
    const end = l.end ?? l.timestamp + 999;
    if (timestamp >= l.timestamp && timestamp < end) return l.text;
  }
  return null;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/**
 * Chord chip. `size="sm"` hangs above a lyric word, `size="md"` fills a
 * chord-only row.
 */
function ChordChip({
  chord,
  active,
  size = "sm",
  onClick,
}: {
  chord: string;
  active?: boolean;
  size?: "sm" | "md";
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick?.();
      }}
      className={[
        "font-pixel border-2 border-black whitespace-nowrap transition-transform hover:-translate-y-0.5",
        size === "sm"
          ? "text-xs sm:text-sm px-1.5 sm:px-2 py-0.5 sm:py-1 leading-tight"
          : "text-sm sm:text-base px-2.5 sm:px-3 py-1",
        active ? "bg-ink text-gold shadow-hard-sm" : chordChipClass(chord),
      ].join(" ")}
    >
      {chord}
    </button>
  );
}

export default function ChordSheet({
  chords,
  words,
  lines,
  romanLines,
  script = "native",
  currentTime,
  activeChord,
  lyricsError,
  onSeek,
}: Props) {
  const rows = useMemo(
    () => buildSheet(chords, words, lines),
    [chords, words, lines]
  );
  const activeRow = activeRowIndex(rows, currentTime);
  const activeRowRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    activeRowRef.current?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });
  }, [activeRow]);

  if (!rows.length) return null;

  return (
    <section className="bg-paper text-ink border-2 border-black shadow-hard px-4 py-6 sm:px-8 sm:py-8">
      {rows.map((row, i) => {
        const active = i === activeRow;
        const rowTone = active
          ? "bg-ink text-paper"
          : "hover:bg-ink/[0.04]";

        if (row.kind === "section") {
          return (
            <p
              key={i}
              className="font-pixel text-ink/55 text-[11px] sm:text-xs tracking-[0.3em] text-center mt-8 mb-4 select-none first:mt-0"
            >
              — {row.label} —
            </p>
          );
        }

        if (row.kind === "chords") {
          return (
            <div
              key={i}
              ref={active ? activeRowRef : undefined}
              onClick={() => onSeek(row.timestamp)}
              className={`-mx-2 sm:-mx-3 px-2 sm:px-3 py-2.5 my-1 cursor-pointer transition-colors rounded-sm ${rowTone}`}
            >
              <div className="flex flex-wrap items-center gap-2 sm:gap-2.5">
                {row.chords.map((ci) => (
                  <ChordChip
                    key={ci}
                    chord={chords[ci].chord}
                    active={ci === activeChord}
                    size="md"
                    onClick={() => onSeek(chords[ci].timestamp)}
                  />
                ))}
              </div>
            </div>
          );
        }

        // lyric row — chords hang above their word
        const hasChords = row.words.some((w) => w.chords.length > 0);
        const roman =
          script === "native" ? null : romanFor(romanLines, row.timestamp);

        return (
          <div
            key={i}
            ref={active ? activeRowRef : undefined}
            onClick={() => onSeek(row.timestamp)}
            className={`-mx-2 sm:-mx-3 px-2 sm:px-3 py-2 my-0.5 cursor-pointer transition-colors rounded-sm group ${rowTone}`}
          >
            <div className="flex items-start gap-3 sm:gap-5">
              {/* timestamp gutter */}
              <span
                className={`shrink-0 w-9 sm:w-11 pt-1 text-right font-cl text-xs select-none ${
                  active
                    ? "text-paper/70"
                    : "text-ink/55 group-hover:text-ink/80"
                }`}
              >
                {formatTime(row.timestamp)}
              </span>

              <div className="flex-1 min-w-0">
                {script === "roman" ? (
                  <>
                    {hasChords && (
                      <div className="flex flex-wrap gap-1 mb-1">
                        {Array.from(
                          new Set(row.words.flatMap((w) => w.chords))
                        ).map((ci) => (
                          <ChordChip
                            key={ci}
                            chord={chords[ci].chord}
                            active={ci === activeChord}
                            onClick={() => onSeek(chords[ci].timestamp)}
                          />
                        ))}
                      </div>
                    )}
                    <p className="font-lyrics text-lg sm:text-2xl leading-relaxed">
                      {roman ?? row.words.map((w) => w.word).join(" ")}
                    </p>
                  </>
                ) : (
                  <>
                    <div
                      className={`flex flex-wrap items-end ${
                        hasChords
                          ? "gap-x-2.5 gap-y-2 sm:gap-x-3"
                          : "gap-x-2 sm:gap-x-2.5"
                      }`}
                    >
                      {row.words.map((w, wi) => {
                        const wordActive = w.chords.includes(activeChord ?? -1);
                        return (
                          <span key={wi} className="inline-flex flex-col items-start">
                            {hasChords && (
                              <span className="flex h-6 sm:h-7 items-end gap-1 mb-0.5">
                                {w.chords.map((ci) => (
                                  <ChordChip
                                    key={ci}
                                    chord={chords[ci].chord}
                                    active={ci === activeChord}
                                    onClick={() => onSeek(chords[ci].timestamp)}
                                  />
                                ))}
                              </span>
                            )}
                            <span
                              className={`font-lyrics text-lg sm:text-2xl leading-snug ${
                                wordActive ? "bg-gold text-ink px-0.5 -mx-0.5" : ""
                              }`}
                            >
                              {w.word}
                            </span>
                          </span>
                        );
                      })}
                    </div>
                    {roman && (
                      <p className="font-cl text-sm sm:text-base italic opacity-70 mt-1">
                        {roman}
                      </p>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
        );
      })}

      {(!words || !words.length) && (!lines || !lines.length) && (
        <p className="font-cl text-ink/65 text-sm mt-5 text-center">
          {lyricsError && lyricsError !== "disabled"
            ? `Lyrics unavailable (${lyricsError}) — showing chords only.`
            : "No vocals detected — chords only."}
        </p>
      )}
      {!(!words || !words.length) && lyricsError && (
        <p className="font-cl text-ink/60 text-xs sm:text-sm mt-5 text-center">
          Lyrics were partially recovered ({lyricsError}).
        </p>
      )}
    </section>
  );
}
