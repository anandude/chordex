"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import { ChordEvent } from "@/lib/api";
import { chordHex } from "@/lib/chordStyle";

interface Props {
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

  const timeCbRef = useRef(onTimeUpdate);
  timeCbRef.current = onTimeUpdate;
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
    setCurrentTime(seekTo);
  }, [seekTo]);

  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) audio.play().catch(() => setError("Playback failed"));
    else audio.pause();
  };

  // chord-tinted scrubber segments across the full track
  const segments = useMemo(() => {
    if (!duration) return [];
    const out: Array<{ start: number; end: number; hex: string }> = [];
    let cursor = 0;
    for (const c of chords) {
      const start = Math.max(c.timestamp, 0);
      const end = Math.min(c.end ?? duration, duration);
      if (start > cursor)
        out.push({ start: cursor, end: start, hex: "#241f31" });
      if (end > start) out.push({ start, end, hex: chordHex(c.chord) });
      cursor = Math.max(cursor, end);
    }
    if (cursor < duration)
      out.push({ start: cursor, end: duration, hex: "#241f31" });
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
    <div className="bg-coal border-2 border-black shadow-hard p-4 sm:p-5">
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
          className="shrink-0 w-14 h-14 sm:w-16 sm:h-16 rounded-full bg-lime border-2 border-black shadow-hard flex items-center justify-center transition-transform hover:-translate-x-0.5 hover:-translate-y-0.5 active:translate-x-[3px] active:translate-y-[3px] active:shadow-none"
        >
          <Image
            src={isPlaying ? "/icons/pause.svg" : "/icons/play.svg"}
            alt=""
            width={30}
            height={30}
            className="w-7 h-7 sm:w-8 sm:h-8"
          />
        </button>

        <div className="flex-1 min-w-0">
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
            className="relative h-9 cursor-pointer touch-none select-none border-2 border-black bg-soot"
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
                  className="h-full border-r border-black/60 last:border-r-0"
                />
              ))}
            </div>
            {/* dim the un-played portion */}
            <div
              className="absolute inset-y-0 right-0 bg-ink/60"
              style={{ left: `${progress}%` }}
            />
            {/* playhead */}
            <div
              className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3.5 h-9 bg-paper border-2 border-black shadow-hard-sm pointer-events-none"
              style={{ left: `${progress}%` }}
            />
          </div>

          {/* Time readout */}
          <div className="flex justify-between mt-2 font-pixel text-paper-dim text-[10px] sm:text-sm whitespace-nowrap shrink-0">
            <span>{formatTime(currentTime)}</span>
            <span>{duration ? formatTime(duration) : "--:--"}</span>
          </div>
        </div>
      </div>

      {error && (
        <p role="alert" className="font-cl text-tomato text-xs mt-3">
          {error}
        </p>
      )}
    </div>
  );
}
