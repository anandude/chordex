// Shared chord color language for the retro-brutalist kit.
// Solid fills + black borders/shadows; type hues: major=violet, minor=teal,
// extensions=gold, N=gray. Active/now highlight = gold.

export type ChordType = "N" | "ext" | "minor" | "major";

export function chordType(chord: string): ChordType {
  if (chord === "N") return "N";
  if (/7|9|11|13|sus|dim|aug|add/.test(chord)) return "ext";
  if (/m(?!aj)/.test(chord)) return "minor";
  return "major";
}

// Raw hex per type — for inline styles (scrubber segments, chart fills)
export const CHORD_HEX: Record<ChordType, string> = {
  major: "#7c5cff",
  minor: "#2dd4bf",
  ext: "#ffb020",
  N: "#4a4556",
};

// Tailwind classes per type — for chip/card UI
export const CHORD_CHIP: Record<ChordType, string> = {
  major: "bg-viol text-ink",
  minor: "bg-mint text-ink",
  ext: "bg-gold text-ink",
  N: "bg-soot text-paper-dim",
};

// Text-only color on dark surfaces (lyrics-sheet chord labels)
export const CHORD_TEXT: Record<ChordType, string> = {
  major: "text-viol",
  minor: "text-mint",
  ext: "text-gold",
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
