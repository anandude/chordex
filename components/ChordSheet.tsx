"use client";

import { useEffect, useMemo, useRef } from "react";
import { ChordEvent, Sheet, SheetRow } from "@/lib/api";
import {
  activeRowIndex,
  activeWordIndex,
  chordsOnlySheet,
  redundantChords,
  romanSegments,
} from "@/lib/chordSheet";
import { chordChipClass } from "@/lib/chordStyle";

interface Props {
  /** Display chords (transposed / Easy Mode) — same length and order as the
   *  backend chord list, so sheet indices stay valid. */
  chords: ChordEvent[];
  sheet?: Sheet;
  script?: "native" | "roman" | "both";
  currentTime: number;
  activeChord: number | null;
  hasLyrics: boolean;
  lyricsError?: string | null;
  /** Click-to-seek. Omitted on a saved song: its audio is gone, so the sheet
   *  is read-only and should not look clickable. */
  onSeek?: (time: number) => void;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/** Chord chip. `size="sm"` hangs above lyrics, `size="md"` fills bar rows. */
function ChordChip({
  chord,
  active,
  faint,
  size = "sm",
  onClick,
}: {
  chord: string;
  active?: boolean;
  faint?: boolean;
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
        "font-display border whitespace-nowrap transition-transform hover:-translate-y-0.5",
        size === "sm"
          ? "text-xs sm:text-sm px-1.5 sm:px-2 py-0.5 sm:py-1 leading-tight rounded-md"
          : "text-sm sm:text-base px-2.5 sm:px-3 py-1 rounded-lg",
        active ? "bg-gold text-white shadow-hard-sm" : chordChipClass(chord),
        faint && !active ? "opacity-45 border-dashed" : "border-transparent",
      ].join(" ")}
    >
      {chord}
    </button>
  );
}

export default function ChordSheet({
  chords,
  sheet,
  script = "native",
  currentTime,
  activeChord,
  hasLyrics,
  lyricsError,
  onSeek,
}: Props) {
  const view = useMemo(() => sheet ?? chordsOnlySheet(chords), [sheet, chords]);
  const labels = useMemo(() => chords.map((c) => c.chord), [chords]);
  const hidden = useMemo(() => redundantChords(view, labels), [view, labels]);
  const rows = view.rows;
  const activeRow = activeRowIndex(rows, currentTime);
  const activeWord = activeWordIndex(rows[activeRow], currentTime);
  const activeRowRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    activeRowRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [activeRow]);

  if (!rows.length) return null;

  const chip = (ci: number, opts: { faint?: boolean; size?: "sm" | "md" } = {}) =>
    labels[ci] === undefined ? null : (
      <ChordChip
        key={ci}
        chord={labels[ci]}
        active={ci === activeChord}
        faint={opts.faint}
        size={opts.size}
        onClick={() => onSeek?.(chords[ci].timestamp)}
      />
    );

  const renderLine = (row: Extract<SheetRow, { kind: "line" }>, isActive: boolean) => {
    const anyChord =
      row.carry !== null ||
      row.gaps.some((g) => g.chords.some((c) => !hidden.has(c))) ||
      row.words.some((w) => w.segs.some((s) => s.chord !== null && !hidden.has(s.chord)));
    const slot = (content: React.ReactNode) =>
      anyChord ? (
        <span className="flex h-7 sm:h-8 items-end gap-1 mb-0.5 pr-1">{content}</span>
      ) : null;
    const textCls = "font-lyrics text-lg sm:text-2xl leading-snug";

    // A chord with no lyric under it: a held note / pause, or the carry chord.
    const gapUnit = (key: string, ids: number[], faint = false) => {
      const vis = ids.filter((c) => faint || !hidden.has(c));
      if (!vis.length) return null;
      return (
        <span key={key} className="inline-flex flex-col">
          {slot(vis.map((c) => chip(c, { faint })))}
          <span className={`${textCls} opacity-30 select-none`} aria-hidden>
            ·
          </span>
        </span>
      );
    };

    const units: React.ReactNode[] = [];
    if (row.carry !== null) units.push(gapUnit("carry", [row.carry], true));
    row.gaps
      .filter((g) => g.after_word < 0)
      .forEach((g, gi) => units.push(gapUnit(`lead${gi}`, g.chords)));

    row.words.forEach((w, k) => {
      const romans = script === "roman" && w.roman ? romanSegments(w) : null;
      const wordActive = isActive && activeWord === k;
      units.push(
        // one word = one unbreakable unit; wrapping happens only between words
        <span key={`w${k}`} className="inline-flex flex-col">
          <span className="inline-flex items-end whitespace-nowrap">
            {w.segs.map((s, si) => {
              const showChord = s.chord !== null && !hidden.has(s.chord);
              const last = si === w.segs.length - 1;
              return (
                <span key={si} className="inline-flex flex-col">
                  {slot(showChord ? chip(s.chord as number) : null)}
                  <span className="flex items-baseline">
                    <span
                      className={`${textCls} ${
                wordActive ? "bg-gold text-white" : ""
                      }`}
                    >
                      {romans ? romans[si] : s.text}
                    </span>
                    {/* mid-word extender when the chord is wider than the syllable */}
                    {!last && (
                      <span className="flex-1 min-w-0 border-b-2 border-dotted border-current opacity-40 mx-px mb-1.5" />
                    )}
                  </span>
                </span>
              );
            })}
          </span>
          {script === "both" && w.roman && (
            <span className="font-cl text-xs sm:text-sm italic opacity-70">{w.roman}</span>
          )}
        </span>
      );
      row.gaps
        .filter((g) => g.after_word === k)
        .forEach((g, gi) => units.push(gapUnit(`g${k}-${gi}`, g.chords)));
    });

    return (
      <div className="flex flex-wrap items-end gap-x-2.5 gap-y-3 sm:gap-x-3">{units}</div>
    );
  };

  return (
    <section className="bg-paper text-ink border border-black/5 shadow-hard rounded-2xl px-4 py-6 sm:px-8 sm:py-8">
      {rows.map((row, i) => {
        const active = i === activeRow;
        const rowTone = active
          ? "bg-ink text-paper"
          : onSeek
            ? "hover:bg-ink/[0.04]"
            : "";

        if (row.kind === "section") {
          return (
            <p
              key={i}
              className="font-display text-ink/55 text-[11px] sm:text-xs tracking-[0.3em] text-center mt-8 mb-4 select-none first:mt-0"
            >
              — {row.label} —
            </p>
          );
        }

        if (row.kind === "bars") {
          const vis = row.chords
            .map((ci, k) => [ci, row.beats[k]] as const)
            .filter(([ci]) => !hidden.has(ci));
          if (!vis.length) return null;
          return (
            <div
              key={i}
              ref={active ? activeRowRef : undefined}
              onClick={onSeek ? () => onSeek(row.t) : undefined}
              className={`-mx-2 sm:-mx-3 px-2 sm:px-3 py-2.5 my-1 transition-colors rounded-sm ${onSeek ? "cursor-pointer" : ""} ${rowTone}`}
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                {vis.map(([ci, beats]) => (
                  <span key={ci} className="inline-flex items-center gap-1.5">
                    {chip(ci, { size: "md" })}
                    <span className="font-cl text-xs opacity-50 tracking-widest" aria-hidden>
                      {"·".repeat(Math.min(7, Math.max(0, beats - 1)))}
                    </span>
                  </span>
                ))}
              </div>
            </div>
          );
        }

        return (
          <div
            key={i}
            ref={active ? activeRowRef : undefined}
            onClick={onSeek ? () => onSeek(row.t) : undefined}
            className={`-mx-2 sm:-mx-3 px-2 sm:px-3 py-2 my-0.5 transition-colors rounded-sm group ${onSeek ? "cursor-pointer" : ""} ${rowTone} ${
              row.chorus ? "border-l-4 border-gold" : ""
            }`}
          >
            <div className="flex items-start gap-3 sm:gap-5">
              <span
                className={`shrink-0 w-9 sm:w-11 pt-1 text-right font-cl text-xs select-none self-end mb-1.5 ${
                  active ? "text-paper/70" : "text-ink/55 group-hover:text-ink/80"
                }`}
              >
                {formatTime(row.t)}
              </span>
              <div className="flex-1 min-w-0">{renderLine(row, active)}</div>
            </div>
          </div>
        );
      })}

      {!hasLyrics && (
        <p className="font-cl text-ink/65 text-sm mt-5 text-center">
          {lyricsError && lyricsError !== "disabled"
            ? `Lyrics unavailable (${lyricsError}) — showing chords only.`
            : "No vocals detected — chords only."}
        </p>
      )}
      {hasLyrics && lyricsError && (
        <p className="font-cl text-ink/60 text-xs sm:text-sm mt-5 text-center">
          Lyrics note: {lyricsError}
        </p>
      )}
    </section>
  );
}
