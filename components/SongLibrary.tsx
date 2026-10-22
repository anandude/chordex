"use client";

/**
 * SongLibrary
 * -----------
 * The songs this browser has transcribed, newest first. Chordex has no
 * accounts: the list is keyed to the device id in localStorage (lib/device.ts),
 * so it only ever shows this browser's songs.
 *
 * Saved songs are sheet-only — the audio is deleted two hours after analysis —
 * so reopening one gives the chord sheet, transpose and Easy Mode, but no
 * play-along.
 */

import { useState } from "react";
import Link from "next/link";
import { Music2, X } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { forgetLibrarySong, listLibrary } from "@/lib/api";
import type { SavedSong } from "@/lib/api";

const LANGUAGES: Record<string, string> = {
  en: "english",
  hi: "hindi",
  ml: "malayalam",
  ta: "tamil",
  te: "telugu",
  kn: "kannada",
};

function clock(seconds: number | null): string {
  if (!seconds || seconds <= 0) return "";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function when(iso: string | null): string {
  if (!iso) return "";
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return "";
  const minutes = Math.round((Date.now() - at) / 60_000);
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} d ago`;
  return new Date(iso).toLocaleDateString();
}

function title(song: SavedSong): string {
  return song.source_name || song.artist || "Untitled song";
}

function meta(song: SavedSong): string {
  return [
    song.key ? `key ${song.key}` : "",
    song.tempo ? `${Math.round(song.tempo)} bpm` : "",
    clock(song.duration),
    song.lyrics_language ? LANGUAGES[song.lyrics_language] ?? song.lyrics_language : "",
    song.n_chords ? `${song.n_chords} chords` : "",
    when(song.created_at),
  ]
    .filter(Boolean)
    .join(" · ");
}

export default function SongLibrary() {
  const queryClient = useQueryClient();
  const [forgetting, setForgetting] = useState<string | null>(null);
  const { data } = useQuery({
    queryKey: ["library"],
    queryFn: listLibrary,
    // A failed listing must never take the upload page down with it.
    retry: 1,
  });

  const forget = async (song: SavedSong) => {
    setForgetting(song.id);
    try {
      await forgetLibrarySong(song.id);
      queryClient.setQueryData(["library"], (old: typeof data) =>
        old ? { ...old, songs: old.songs.filter((s) => s.id !== song.id) } : old
      );
    } catch {
      // Leave the row in place: it is still on the server.
    } finally {
      setForgetting(null);
    }
  };

  // No store configured on the server, or nothing saved yet: stay out of the way.
  if (!data?.enabled || data.songs.length === 0) return null;

  return (
    <section className="mt-8 animate-pop" aria-labelledby="library-heading">
      <div className="flex items-baseline justify-between mb-3 px-1">
        <h2
          id="library-heading"
          className="font-cl text-paper-dim text-[11px] uppercase tracking-[0.2em]"
        >
          your songs
        </h2>
        <span className="font-cl text-paper-dim/70 text-[11px]">
          {data.songs.length} saved · this browser only
        </span>
      </div>

      <ul className="bg-coal border border-white/10 shadow-hard rounded-2xl divide-y divide-white/5 overflow-hidden">
        {data.songs.map((song) => (
          <li key={song.id} className="flex items-center">
            <Link
              href={`/results/${song.id}`}
              className="flex-1 min-w-0 flex items-center gap-3 pl-3 pr-1 py-3 hover:bg-white/5 transition-colors"
            >
              <span
                aria-hidden
                className="shrink-0 w-9 h-9 rounded-full bg-gold/15 text-gold flex items-center justify-center"
              >
                <Music2 strokeWidth={2.5} className="w-4 h-4" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate font-semibold text-paper text-sm">
                  {title(song)}
                </span>
                <span className="block truncate font-cl text-paper-dim text-[11px] tracking-wide">
                  {meta(song)}
                </span>
              </span>
            </Link>
            <button
              type="button"
              onClick={() => forget(song)}
              disabled={forgetting === song.id}
              aria-label={`Forget ${title(song)}`}
              title="Remove from your songs"
              className="shrink-0 mr-2 w-9 h-9 rounded-full text-paper-dim/60 hover:text-tomato hover:bg-tomato/10 flex items-center justify-center transition-colors disabled:opacity-40"
            >
              <X aria-hidden strokeWidth={2.5} className="w-4 h-4" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
