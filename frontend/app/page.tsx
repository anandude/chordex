"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { uploadAudio } from "@/lib/api";

const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20 MB
const ALLOWED_EXTS = [".mp3", ".wav", ".ogg", ".flac"];

const LANGUAGES = [
  { value: "auto", label: "Auto-detect" },
  { value: "en", label: "English" },
  { value: "hi", label: "हिन्दी · Hindi" },
  { value: "ml", label: "മലയാളം · Malayalam" },
  { value: "ta", label: "தமிழ் · Tamil" },
  { value: "te", label: "తెలుగు · Telugu" },
  { value: "kn", label: "ಕನ್ನಡ · Kannada" },
];

export default function Home() {
  const router = useRouter();
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [language, setLanguage] = useState("auto");
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);
      const ext = "." + (file.name.split(".").pop() ?? "").toLowerCase();
      if (!ALLOWED_EXTS.includes(ext)) {
        setError(`Unsupported file type. Allowed: ${ALLOWED_EXTS.join(", ")}`);
        return;
      }
      if (file.size > MAX_FILE_SIZE) {
        setError("File too large. Maximum size is 20 MB.");
        return;
      }
      setIsUploading(true);
      try {
        const { job_id } = await uploadAudio(file, language, {
          title: title.trim() || undefined,
          artist: artist.trim() || undefined,
        });
        router.push(`/results/${job_id}`);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Upload failed. Please try again."
        );
        setIsUploading(false);
      }
    },
    [router, language, title, artist]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  return (
    <main className="min-h-screen flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-lg animate-pop">
        {/* Wordmark + tagline */}
        <div className="mb-10 flex flex-col items-center">
          <Image
            src="/logo.webp"
            alt="ChordLens"
            width={340}
            height={227}
            priority
            className="w-64 sm:w-80 h-auto drop-shadow-[6px_6px_0_rgba(0,0,0,0.9)]"
          />
          <p className="font-cl text-paper-dim text-sm sm:text-base mt-4 text-center">
            drop a song → get a playable chord sheet
          </p>
        </div>

        {/* Drop zone — paper card, lifts when dragging */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          onClick={() => !isUploading && fileInputRef.current?.click()}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              if (!isUploading) fileInputRef.current?.click();
            }
          }}
          aria-label="Upload an audio file"
          className={[
            "relative bg-paper border-2 border-black p-10 sm:p-12 text-center transition-transform duration-150",
            isDragging
              ? "-translate-x-1 -translate-y-1 shadow-hard-lg"
              : "shadow-hard hover:-translate-x-0.5 hover:-translate-y-0.5",
            isUploading ? "opacity-80 cursor-wait" : "cursor-pointer",
          ].join(" ")}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".mp3,.wav,.ogg,.flac"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFile(file);
              e.target.value = "";
            }}
          />

          {isUploading ? (
            <div className="flex flex-col items-center gap-5 py-4">
              {/* equalizer bars */}
              <div className="flex items-end gap-1.5 h-10" aria-hidden>
                {[0, 1, 2, 3, 4].map((i) => (
                  <span
                    key={i}
                    className="w-2.5 bg-ink animate-eq origin-bottom"
                    style={{ height: "100%", animationDelay: `${i * 0.12}s` }}
                  />
                ))}
              </div>
              <p className="font-pixel text-ink text-lg tracking-wide">
                UPLOADING…
              </p>
            </div>
          ) : (
            <>
              <Image
                src="/icons/note.svg"
                alt=""
                width={56}
                height={56}
                className="mx-auto mb-5 w-12 h-12"
              />
              <p className="text-ink font-bold text-xl sm:text-2xl mb-2 tracking-tight">
                {isDragging ? "Drop it!" : "Drop your audio file here"}
              </p>
              <p className="text-ink/70 text-sm sm:text-base">
                or click to browse
              </p>
              <p className="font-cl text-ink/60 text-xs sm:text-sm mt-5">
                MP3 · WAV · OGG · FLAC &nbsp;·&nbsp; max 20 MB
              </p>
            </>
          )}
        </div>

        {/* Optional details — grouped in one panel so the drop zone stays hero */}
        <div className="mt-5 bg-coal border-2 border-black shadow-hard p-4 sm:p-5">
          <p className="font-cl text-paper-dim text-[11px] uppercase tracking-[0.2em] mb-3.5">
            Song details · optional
          </p>

          <div className="grid grid-cols-2 gap-3">
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Song title"
              aria-label="Song title"
              className="w-full bg-paper text-ink text-sm font-semibold border-2 border-black shadow-hard-sm px-3 py-2.5 placeholder:text-ink/45 focus:outline-none focus:-translate-y-px transition-transform"
            />
            <input
              type="text"
              value={artist}
              onChange={(e) => setArtist(e.target.value)}
              placeholder="Artist"
              aria-label="Artist"
              className="w-full bg-paper text-ink text-sm font-semibold border-2 border-black shadow-hard-sm px-3 py-2.5 placeholder:text-ink/45 focus:outline-none focus:-translate-y-px transition-transform"
            />
          </div>
          <p className="font-cl text-paper-dim text-xs mt-3 leading-relaxed">
            title + artist let us fetch verified lyrics instead of transcribing
          </p>

          <div className="mt-4 pt-4 border-t-2 border-soot">
            <label
              htmlFor="language"
              className="block font-cl text-paper-dim text-[11px] uppercase tracking-[0.2em] mb-2.5"
            >
              Lyrics language
            </label>
            <select
              id="language"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="w-full bg-paper text-ink text-sm font-semibold border-2 border-black shadow-hard-sm px-3 py-2.5 cursor-pointer appearance-none pr-9 min-h-11 bg-[url('data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20width%3D%2210%22%20height%3D%226%22%3E%3Cpath%20d%3D%22M0%200h10L5%206z%22%20fill%3D%22%23000%22%2F%3E%3C%2Fsvg%3E')] bg-no-repeat bg-[right_0.75rem_center] hover:-translate-y-px transition-transform"
            >
              {LANGUAGES.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
            {language === "ml" && (
              <p className="font-cl text-paper-dim text-xs mt-2.5 leading-relaxed">
                Hindi & Malayalam use a larger lyric model and vocal separation
                — analysis can take a few extra minutes.
              </p>
            )}
          </div>
        </div>

        {/* Error message */}
        {error && (
          <div
            role="alert"
            className="mt-4 p-4 bg-tomato border-2 border-black shadow-hard-sm text-ink font-semibold text-sm sm:text-base"
          >
            {error}
          </div>
        )}
      </div>

      <p className="mt-10 font-cl text-paper-dim text-xs sm:text-sm text-center tracking-wide">
        chords: Chordino / MIR · lyrics: Whisper · ready in ~1–3 min
      </p>
    </main>
  );
}
