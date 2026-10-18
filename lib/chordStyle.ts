// Shared chord color language for the Chordex kit.
// Soft fills + hairline borders; type hues: major=terracotta, minor=sage,
// extensions=dusty blue, N=gray. Active/now highlight = terracotta.

export type ChordType = "N" | "ext" | "minor" | "major";

export function chordType(chord: string): ChordType {
  if (chord === "N") return "N";
  if (/7|9|11|13|sus|dim|aug|add/.test(chord)) return "ext";
  if (/m(?!aj)/.test(chord)) return "minor";
  return "major";
}

// Raw hex per type — for inline styles (scrubber segments, chart fills)
export const CHORD_HEX: Record<ChordType, string> = {
  major: "#d89b6f",
  minor: "#7fc4b4",
  ext: "#97abc9",
  N: "#3a3a3a",
};

// Tailwind classes per type — for chip/card UI
export const CHORD_CHIP: Record<ChordType, string> = {
  major: "bg-viol text-ink",
  minor: "bg-mint text-ink",
  ext: "bg-dusk text-ink",
  N: "bg-soot text-paper-dim",
};

// Text-only color on dark surfaces (lyrics-sheet chord labels)
export const CHORD_TEXT: Record<ChordType, string> = {
  major: "text-viol",
  minor: "text-mint",
  ext: "text-dusk",
  N: "text-paper-dim",
};

export function chordHex(chord: string): string {
  return CHORD_HEX[chordType(chord)];
}

export function chordChipClass(chord: string): string {
  return CHORD_CHIP[chordType(chord)];
}

export function chordTextClass(chord: string): string {
  return CHORD_TEXT[chordType(chord)];
}
