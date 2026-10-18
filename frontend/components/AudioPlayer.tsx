"use client";

import { Ref, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { Pause, Play } from "lucide-react";
import { ChordEvent } from "@/lib/api";
import { chordHex } from "@/lib/chordStyle";

/** Lets other controls (the sticky mobile bar) drive playback. */
export interface PlayerHandle {
  toggle: () => void;
}

interface Props {
  ref?: Ref<PlayerHandle>;
  src: string;
  chords: ChordEvent[];
  onTimeUpdate?: (time: number) => void;
  onPlayingChange?: (playing: boolean) => void;
  seekTo?: number | null;
}

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds)) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function AudioPlayer({
  ref,
  src,
  chords,
  onTimeUpdate,
  onPlayingChange,
  seekTo,
}: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const trackRef = useRef<HTMLDivElement>(null);
  const rafRef = useRef<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [scrubbing, setScrubbing] = useState(false);

  // keep the latest callback in a ref so the rAF loop never holds a stale one
  const timeCbRef = useRef(onTimeUpdate);
  useEffect(() => {
    timeCbRef.current = onTimeUpdate;
  }, [onTimeUpdate]);
  // rAF loop drives both the page playhead and the local scrubber
  const tick = () => {
    if (audioRef.current) {
      const t = audioRef.current.currentTime;
      timeCbRef.current?.(t);
      setCurrentTime(t);
    }
    rafRef.current = requestAnimationFrame(tick);
  };
  const stopLoop = () => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  };
  const startLoop = () => {
    if (rafRef.current == null) rafRef.current = requestAnimationFrame(tick);
  };
  useEffect(() => stopLoop, []);

  useEffect(() => {
    if (seekTo == null || !audioRef.current) return;
    audioRef.current.currentTime = seekTo;
    timeCbRef.current?.(seekTo);
    // the local scrubber catches up in onSeeked (a few ms later)
  }, [seekTo]);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) audio.play().catch(() => setError("Playback failed"));
    else audio.pause();
  };

  useImperativeHandle(ref, () => ({ toggle: togglePlay }));

  // Space = play/pause anywhere on the page, unless the user is typing or a
  // button has focus (Space already activates that button).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space" || e.repeat || e.metaKey || e.ctrlKey || e.altKey) return;
      const el = e.target as HTMLElement | null;
      if (el?.closest("input, textarea, select, button, [contenteditable], [role=slider]")) return;
      e.preventDefault();
      const audio = audioRef.current;
      if (!audio) return;
      if (audio.paused) audio.play().catch(() => setError("Playback failed"));
      else audio.pause();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // chord-tinted scrubber segments across the full track
  const segments = useMemo(() => {
    if (!duration) return [];
    const out: Array<{ start: number; end: number; hex: string }> = [];
    let cursor = 0;
    for (const c of chords) {
      const start = Math.max(c.timestamp, 0);
      const end = Math.min(c.end ?? duration, duration);
      if (start > cursor)
        out.push({ start: cursor, end: start, hex: "#2b2b2b" });
      if (end > start) out.push({ start, end, hex: chordHex(c.chord) });
      cursor = Math.max(cursor, end);
    }
    if (cursor < duration)
      out.push({ start: cursor, end: duration, hex: "#2b2b2b" });
    return out;
  }, [chords, duration]);

  const scrubTo = (clientX: number) => {
    const track = trackRef.current;
    const audio = audioRef.current;
    if (!track || !audio || !duration) return;
    const rect = track.getBoundingClientRect();
    const ratio = Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1);
    const t = ratio * duration;
    audio.currentTime = t;
    timeCbRef.current?.(t);
    setCurrentTime(t);
  };

  const progress = duration ? (currentTime / duration) * 100 : 0;

  return (
    <div className="bg-coal border border-white/10 shadow-hard rounded-2xl p-4 sm:p-5">
      <audio
        ref={audioRef}
        src={src}
        preload="metadata"
        className="hidden"
        onPlay={() => {
          startLoop();
          setIsPlaying(true);
          onPlayingChange?.(true);
        }}
        onPause={() => {
          stopLoop();
          setIsPlaying(false);
          onPlayingChange?.(false);
          if (audioRef.current) {
            timeCbRef.current?.(audioRef.current.currentTime);
            setCurrentTime(audioRef.current.currentTime);
          }
        }}
        onEnded={() => {
          stopLoop();
          setIsPlaying(false);
          onPlayingChange?.(false);
        }}
        onSeeked={(e) => {
          const t = e.currentTarget.currentTime;
          timeCbRef.current?.(t);
          setCurrentTime(t);
        }}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onDurationChange={(e) => setDuration(e.currentTarget.duration)}
        onError={() =>
          setError("Could not load audio (may have expired from storage).")
        }
      />

      <div className="flex items-center gap-4 sm:gap-5">
        {/* Play / pause */}
        <button
          type="button"
          onClick={togglePlay}
          aria-label={isPlaying ? "Pause" : "Play"}
          className="shrink-0 w-14 h-14 sm:w-16 sm:h-16 rounded-full bg-lime shadow-hard flex items-center justify-center transition-transform hover:opacity-85 active:opacity-70"
        >
          {isPlaying ? (
            <Pause aria-hidden fill="currentColor" className="w-7 h-7 sm:w-8 sm:h-8 text-ink" />
          ) : (
            <Play aria-hidden fill="currentColor" className="w-7 h-7 sm:w-8 sm:h-8 text-ink translate-x-0.5" />
          )}
        </button>

        <div className="flex-1 min-w-0">
          {/* Time readout — elapsed left, total right, above the bar */}
          <div className="flex items-baseline justify-between gap-3 mb-2 font-cl">
            <span className="text-paper text-sm sm:text-base">
              {formatTime(currentTime)}
            </span>
            <span className="text-paper-dim text-xs sm:text-sm">
              {duration ? formatTime(duration) : "--:--"}
            </span>
          </div>

          {/* Chord-aware scrubber */}
          <div
            ref={trackRef}
            role="slider"
            aria-label="Seek"
            aria-valuemin={0}
            aria-valuemax={Math.round(duration)}
            aria-valuenow={Math.round(currentTime)}
            tabIndex={0}
            onKeyDown={(e) => {
              const audio = audioRef.current;
              if (!audio) return;
              if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
                e.preventDefault();
                const dir = e.key === "ArrowRight" ? 1 : -1;
                const t = Math.min(
                  Math.max(audio.currentTime + dir * 5, 0),
                  duration || 0
                );
                audio.currentTime = t;
                timeCbRef.current?.(t);
                setCurrentTime(t);
              }
            }}
            onPointerDown={(e) => {
              e.preventDefault();
              trackRef.current?.setPointerCapture(e.pointerId);
              setScrubbing(true);
              scrubTo(e.clientX);
            }}
            onPointerMove={(e) => scrubbing && scrubTo(e.clientX)}
            onPointerUp={() => setScrubbing(false)}
            onPointerCancel={() => setScrubbing(false)}
            className="relative h-9 cursor-pointer touch-none select-none border border-white/10 rounded-lg bg-soot"
          >
            {/* chord segments */}
            <div className="absolute inset-0 flex">
              {segments.map((s, i) => (
                <div
                  key={i}
                  style={{
                    width: `${((s.end - s.start) / (duration || 1)) * 100}%`,
                    backgroundColor: s.hex,
                  }}
                  className="h-full border-r border-black/30 last:border-r-0"
                />
              ))}
            </div>
            {/* dim the un-played portion (kept light so chord colours read) */}
            <div
              className="absolute inset-y-0 right-0 bg-ink/45"
              style={{ left: `${progress}%` }}
            />
            {/* playhead */}
            <div
              className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-9 bg-paper rounded-full shadow-hard-sm pointer-events-none"
              style={{ left: `${progress}%` }}
            />
          </div>

          <p className="mt-2 font-cl text-paper-dim/80 text-[11px] sm:text-xs">
            <span className="lg:hidden">coloured by chord — tap to jump</span>
            <span className="hidden lg:inline">tap to jump · space plays</span>
          </p>
        </div>
      </div>

      {error && (
        <p role="alert" className="font-cl text-tomato text-xs sm:text-sm mt-3">
          {error}
        </p>
      )}
    </div>
  );
}
