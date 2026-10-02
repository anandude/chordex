"use client";

import { ChordEvent } from "@/lib/api";
import { chordTextClass } from "@/lib/chordStyle";

interface Props {
  chords: ChordEvent[];
  activeIndex: number | null;
  currentTime: number;
  playing: boolean;
  onSeek?: (timestamp: number) => void;
}

const PROGRESS_BLOCKS = 14;

/** "N" is the engine's no-chord marker — never show it to the player. */
function chordLabel(chord: string): string {
  return chord === "N" ? "—" : chord;
}

export default function NowNextBar({
  chords,
  activeIndex,
  currentTime,
  playing,
  onSeek,
}: Props) {
  if (!chords.length) return null;

  const hasActive = activeIndex != null;
  const now = chords[hasActive ? activeIndex! : 0];
  const next = chords[(hasActive ? activeIndex! : -1) + 1];

  const nowStart = now.timestamp;
  const nowEnd = now.end ?? (next ? next.timestamp : nowStart + 999);
  const nowProgress =
    nowEnd > nowStart
      ? Math.min(
          Math.max((currentTime - nowStart) / (nowEnd - nowStart), 0),
          1
        )
      : 1;

  const nextIn = next != null ? Math.max(next.timestamp - currentTime, 0) : null;
  const filled = Math.round(nowProgress * PROGRESS_BLOCKS);

  const nowActive = hasActive && playing;

  return (
    <div
      // Sticky playhead header: solid background (not translucent) so pinned
      // content never visually collides with the sheet scrolling under it.
      className={`sticky top-0 z-20 -mx-1 px-1 pt-3 pb-2 bg-ink shadow-hard transition-opacity ${
        playing ? "" : "opacity-70"
      }`}
    >
      <div className="grid grid-cols-[1fr_auto_1fr] items-stretch gap-2 sm:gap-4">
        {/* NOW — gold slab when live */}
        <button
          type="button"
          onClick={() => onSeek?.(nowStart)}
          aria-label={`Current chord ${chordLabel(now.chord)}. Restart it.`}
          className={[
            "text-left border-2 border-black px-3 py-2.5 sm:px-5 sm:py-3 transition-all",
            nowActive
              ? "bg-gold text-ink shadow-hard"
              : "bg-paper text-ink shadow-hard-sm hover:-translate-y-0.5",
          ].join(" ")}
        >
          <p
            className={`font-cl text-[11px] sm:text-xs uppercase tracking-[0.2em] mb-1 ${
              nowActive ? "text-ink/70" : "text-ink/60"
            }`}
          >
            {hasActive ? (nowActive ? "▶ Now" : "Now") : "Up first"}
          </p>
          <p
            aria-live="polite"
            className={`font-pixel leading-none ${
              now.chord.length > 5 ? "text-3xl sm:text-5xl" : "text-4xl sm:text-6xl"
            }`}
          >
            {chordLabel(now.chord)}
          </p>
          {/* segmented progress through the chord */}
          <div className="flex gap-[3px] mt-2" aria-hidden>
            {Array.from({ length: PROGRESS_BLOCKS }).map((_, i) => (
              <span
                key={i}
                className={`h-1.5 flex-1 border border-black/70 ${
                  i < filled ? (nowActive ? "bg-ink" : "bg-ink/70") : "bg-ink/15"
                }`}
              />
            ))}
          </div>
        </button>

        {/* Arrow */}
        <div className="flex items-center self-center" aria-hidden>
          <span
            className={`font-pixel text-2xl sm:text-3xl ${
              next ? "text-paper" : "text-transparent"
            }`}
          >
            →
          </span>
        </div>

        {/* NEXT */}
        {next ? (
          <button
            type="button"
            onClick={() => onSeek?.(next.timestamp)}
            aria-label={`Next chord ${chordLabel(next.chord)}. Jump to it.`}
            className="text-right border-2 border-black bg-coal px-3 py-2.5 sm:px-5 sm:py-3 text-paper shadow-hard-sm hover:-translate-y-0.5 transition-all"
          >
            <p className="font-cl text-[11px] sm:text-xs uppercase tracking-[0.2em] text-paper-dim mb-1">
              Next
            </p>
            <p
              className={`font-pixel leading-none ${
                next.chord.length > 5 ? "text-2xl sm:text-4xl" : "text-3xl sm:text-5xl"
              } ${chordTextClass(next.chord)}`}
            >
              {chordLabel(next.chord)}
            </p>
            <p className="font-pixel text-xs sm:text-sm text-paper-dim mt-2">
              {nextIn != null && nextIn > 0.05 && nextIn <= 5
                ? `IN ${nextIn.toFixed(1)}S`
                : "\u00A0"}
            </p>
          </button>
        ) : (
          <div className="text-right border-2 border-black bg-coal px-3 py-2.5 sm:px-5 sm:py-3 text-paper shadow-hard-sm">
            <p className="font-cl text-[11px] sm:text-xs uppercase tracking-[0.2em] text-paper-dim mb-1">
              Next
            </p>
            <p className="font-pixel text-3xl sm:text-5xl leading-none text-paper-dim/70">
              —
            </p>
            <p className="text-xs sm:text-sm mt-2 font-pixel text-transparent">
              {"\u00A0"}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
