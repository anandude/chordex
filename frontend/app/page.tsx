"use client";

import { useCallback, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { uploadAudio } from "@/lib/api";

const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20 MB
const ALLOWED_EXTS = [".mp3", ".wav", ".ogg", ".flac"];

export default function Home() {
  const router = useRouter();
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
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
        const { job_id } = await uploadAudio(file);
        router.push(`/results/${job_id}`);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Upload failed. Please try again."
        );
        setIsUploading(false);
      }
    },
    [router]
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
    <main className="min-h-screen bg-gray-950 flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-lg">
        {/* Header */}
        <div className="text-center mb-10">
          <h1 className="text-5xl font-bold text-white mb-3 tracking-tight">
            ChordLens
          </h1>
          <p className="text-gray-400 text-lg">
            Upload a song. Get every chord with timestamps.
          </p>
        </div>

        {/* Drop zone */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          onClick={() => !isUploading && fileInputRef.current?.click()}
          className={[
            "relative border-2 border-dashed rounded-2xl p-14 text-center transition-all",
            isDragging
              ? "border-blue-400 bg-blue-950/30 scale-[1.01]"
              : "border-gray-700 hover:border-gray-500 bg-gray-900/50",
            isUploading ? "opacity-70 cursor-not-allowed" : "cursor-pointer",
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
            <div className="flex flex-col items-center gap-4">
              <div className="w-10 h-10 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
              <p className="text-gray-300 font-medium">Uploading…</p>
            </div>
          ) : (
            <>
              <div className="text-5xl mb-5 select-none">🎵</div>
              <p className="text-white font-semibold text-lg mb-2">
                {isDragging ? "Drop it here" : "Drop your audio file here"}
              </p>
              <p className="text-gray-500 text-sm">or click to browse</p>
              <p className="text-gray-600 text-xs mt-5">
                MP3 · WAV · OGG · FLAC &nbsp;·&nbsp; Max 20 MB
              </p>
            </>
          )}
        </div>

        {/* Error message */}
        {error && (
          <div className="mt-4 p-4 bg-red-900/40 border border-red-700 rounded-xl text-red-300 text-sm">
            {error}
          </div>
        )}
      </div>

      <p className="mt-12 text-gray-700 text-xs text-center">
        Chordino + MIR pipeline · Results ready in ~10–40 s
      </p>
    </main>
  );
}
