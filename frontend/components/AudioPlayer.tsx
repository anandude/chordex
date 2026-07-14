"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  src: string;
  onTimeUpdate?: (time: number) => void;
  seekTo?: number | null;
}

export default function AudioPlayer({ src, onTimeUpdate, seekTo }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (seekTo == null || !audioRef.current) return;
    audioRef.current.currentTime = seekTo;
  }, [seekTo]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <p className="text-sm font-medium text-gray-400 mb-3">Playback</p>
      <audio
        ref={audioRef}
        src={src}
        controls
        className="w-full"
        preload="metadata"
        onTimeUpdate={(e) => onTimeUpdate?.(e.currentTarget.currentTime)}
        onError={() =>
          setError("Could not load audio (may have expired from storage).")
        }
      />
      {error && <p className="text-xs text-red-400 mt-2">{error}</p>}
      <p className="text-[11px] text-gray-600 mt-2">
        Click a chord card to jump to that moment.
      </p>
    </div>
  );
}
