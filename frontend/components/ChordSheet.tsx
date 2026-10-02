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

function ChordChip({
  chord,
  active,
  small,
  onClick,
}: {
  chord: string;
  active?: boolean;
  small?: boolean;
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
        small ? "text-[11px] sm:text-xs px-1.5 py-0.5 leading-tight" : "text-sm sm:text-base px-2.5 py-1",
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
  const rows = useMemo(() => buildSheet(chords, words, lines), [chords, words, lines]);
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
    <section className="bg-paper text-ink border-2 border-black shadow-hard px-4 py-5 sm:px-8 sm:py-7">
      {rows.map((row, i) => {
        const active = i === activeRow;

        if (row.kind === "section") {
          return (
            <p
              key={i}
              className="font-pixel text-ink/60 text-xs sm:text-sm tracking-[0.25em] text-center my-5 select-none"
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
              className={`flex flex-wrap items-center gap-2 sm:gap-2.5 py-2.5 cursor-pointer rounded-sm transition-colors ${
                active ? "bg-ink/90 px-3 -mx-1 py-3" : "hover:bg-ink/5 px-3 -mx-1"
              }`}
            >
              {row.chords.map((ci) => (
                <ChordChip
                  key={ci}
                  chord={chords[ci].chord}
                  active={ci === activeChord}
                  onClick={() => onSeek(chords[ci].timestamp)}
                />
              ))}
            </div>
          );
        }

        // lyric row — chords hang above their words
        const hasChords = row.words.some((w) => w.chords.length > 0);
        const roman = script === "native" ? null : romanFor(romanLines, row.timestamp);
        return (
          <div
            key={i}
            ref={active ? activeRowRef : undefined}
            onClick={() => onSeek(row.timestamp)}
            className={`relative cursor-pointer rounded-sm transition-colors group ${
              hasChords ? "pt-7 sm:pt-8" : "pt-0.5"
            } pb-1.5 -mx-2 px-2 ${
              active
                ? "bg-ink text-paper"
                : "hover:bg-ink/[0.04]"
            }`}
          >
            {/* timestamp gutter */}
            <span
              className={`absolute left-2 top-0 font-cl text-[10px] ${
                active ? "text-paper/70" : "text-ink/45 group-hover:text-ink/70"
              } ${hasChords ? "-top-0.5" : "top-1"} hidden sm:block select-none`}
            >
              {formatTime(row.timestamp)}
            </span>

            {script === "roman" ? (
              <>
                {hasChords && (
                  <span className="flex flex-wrap gap-1 mb-1 sm:ml-14">
                    {Array.from(new Set(row.words.flatMap((w) => w.chords))).map(
                      (ci) => (
                        <ChordChip
                          key={ci}
                          chord={chords[ci].chord}
                          active={ci === activeChord}
                          small
                          onClick={() => onSeek(chords[ci].timestamp)}
                        />
                      )
                    )}
                  </span>
                )}
                <p className="font-lyrics text-base sm:text-xl leading-[1.7] sm:ml-14">
                  {roman ??
                    row.words.map((w) => w.word).join(" ")}
                </p>
              </>
            ) : (
              <>
                <p className="font-lyrics text-base sm:text-xl leading-[1.7] sm:ml-14">
                  {row.words.map((w, wi) =>
                    w.chords.length ? (
                      <span key={wi} className="relative inline-block">
                        <span className="absolute -top-7 sm:-top-8 left-0 z-10 flex gap-1">
                          {w.chords.map((ci) => (
                            <ChordChip
                              key={ci}
                              chord={chords[ci].chord}
                              active={ci === activeChord}
                              small
                              onClick={() => onSeek(chords[ci].timestamp)}
                            />
                          ))}
                        </span>
                        <span
                          className={
                            w.chords.includes(activeChord ?? -1)
                              ? "bg-gold/80 px-0.5 -mx-0.5"
                              : ""
                          }
                        >
                          {w.word}
                        </span>
                      </span>
                    ) : (
                      <span key={wi}>{w.word}</span>
                    )
                  )}{" "}
                </p>
                {roman && (
                  <p className="font-cl text-sm sm:text-base italic opacity-70 sm:ml-14 mt-0.5">
                    {roman}
                  </p>
                )}
              </>
            )}
          </div>
        );
      })}

      {(!words || !words.length) && (!lines || !lines.length) && (
        <p className="font-cl text-ink/65 text-xs mt-4 text-center">
          {lyricsError && lyricsError !== "disabled"
            ? `Lyrics unavailable (${lyricsError}) — showing chords only.`
            : "No vocals detected — chords only."}
        </p>
      )}
      {!(!words || !words.length) && lyricsError && (
        <p className="font-cl text-ink/60 text-[11px] mt-4 text-center">
          Lyrics were partially recovered ({lyricsError}).
        </p>
      )}
    </section>
  );
}
