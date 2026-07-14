"use client";

import { ChordEvent } from "@/lib/api";

function getChordStyle(chord: string, active: boolean): string {
  const base = active
    ? "ring-2 ring-amber-400 scale-105 shadow-lg shadow-amber-900/30"
    : "";

  if (chord === "N")
    return `${base} bg-gray-800/60 text-gray-500 border-gray-700`;

  // Dominant / maj7 / extensions
  if (/7|9|11|13|sus|dim|aug|add/.test(chord))
    return `${base} bg-emerald-900/40 text-emerald-300 border-emerald-700/60`;

  // Minor
  if (/m(?!aj)/.test(chord))
    return `${base} bg-purple-900/40 text-purple-300 border-purple-700/60`;

  // Major (default)
  return `${base} bg-blue-900/40 text-blue-300 border-blue-700/60`;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

interface Props {
  chords: ChordEvent[];
  activeIndex?: number | null;
  onSelect?: (index: number, timestamp: number) => void;
}

export default function ChordTimeline({
  chords,
  activeIndex = null,
  onSelect,
}: Props) {
  if (chords.length === 0) return null;

  return (
    <section>
      <h2 className="text-sm font-medium text-gray-500 uppercase tracking-widest mb-4">
        Chord Progression
      </h2>

      {/* Desktop: horizontal scroll */}
      <div className="hidden sm:flex gap-3 overflow-x-auto pb-3 scroll-smooth">
        {chords.map((event, i) => (
          <button
            key={`${event.timestamp}-${event.chord}-${i}`}
            type="button"
            onClick={() => onSelect?.(i, event.timestamp)}
            className={[
              "flex-shrink-0 border rounded-xl px-4 py-3 text-center min-w-[80px] transition-all",
              getChordStyle(event.chord, activeIndex === i),
              onSelect ? "cursor-pointer hover:brightness-110" : "",
            ].join(" ")}
          >
            <p className="text-xs opacity-50 mb-1 font-mono">
              {formatTime(event.timestamp)}
              {event.end != null ? `–${formatTime(event.end)}` : ""}
            </p>
            <p className="text-xl font-bold tracking-tight">{event.chord}</p>
            {event.confidence != null && event.confidence < 0.55 && (
              <p className="text-[10px] opacity-40 mt-1">low conf</p>
            )}
          </button>
        ))}
      </div>

      {/* Mobile: vertical list */}
      <div className="sm:hidden flex flex-col gap-2">
        {chords.map((event, i) => (
          <button
            key={`${event.timestamp}-${event.chord}-${i}`}
            type="button"
            onClick={() => onSelect?.(i, event.timestamp)}
            className={[
              "flex items-center justify-between border rounded-lg px-4 py-3 transition-all text-left",
              getChordStyle(event.chord, activeIndex === i),
            ].join(" ")}
          >
            <span className="text-sm font-mono opacity-50">
              {formatTime(event.timestamp)}
            </span>
            <span className="text-xl font-bold tracking-tight">
              {event.chord}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}
