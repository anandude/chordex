/**
 * transpose.ts
 * ------------
 * Client-side chord transposition — mirrors backend transposer.py.
 */

const NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];

const FLAT_TO_SHARP: Record<string, string> = {
  Db: "C#",
  Eb: "D#",
  Fb: "E",
  Gb: "F#",
  Ab: "G#",
  Bb: "A#",
  Cb: "B",
};

function normalizeRoot(raw: string): string | null {
  if (!raw) return null;
  if (raw.length >= 2 && (raw[1] === "#" || raw[1] === "b")) {
    const root = FLAT_TO_SHARP[raw.slice(0, 2)] ?? raw.slice(0, 2);
    return NOTES.includes(root) ? root : null;
  }
  const root = raw[0].toUpperCase();
  return NOTES.includes(root) ? root : null;
}

function parseChord(chord: string): [string, string, string | null] {
  if (chord === "N") return ["N", "", null];

  let body = chord;
  let bass: string | null = null;
  if (chord.includes("/")) {
    const [b, bassRaw] = chord.split("/", 2);
    body = b;
    bass = normalizeRoot(bassRaw);
  }

  if (body.length >= 2 && (body[1] === "#" || body[1] === "b")) {
    const root = FLAT_TO_SHARP[body.slice(0, 2)] ?? body.slice(0, 2);
    return [root, body.slice(2), bass];
  }
  return [body[0], body.slice(1), bass];
}

export function transposeChord(chord: string, semitones: number): string {
  if (chord === "N") return "N";
  const [root, quality, bass] = parseChord(chord);
  const idx = NOTES.indexOf(root);
  if (idx === -1) return chord;
  const newIdx = (((idx + semitones) % 12) + 12) % 12;
  let result = NOTES[newIdx] + quality;
  if (bass) {
    const bIdx = NOTES.indexOf(bass);
    if (bIdx !== -1) {
      const newBass = NOTES[(((bIdx + semitones) % 12) + 12) % 12];
      result += "/" + newBass;
    }
  }
  return result;
}

export function transposeProgression<
  T extends { timestamp: number; chord: string },
>(chords: T[], semitones: number): T[] {
  if (semitones === 0) return chords;
  return chords.map((item) => ({
    ...item,
    chord: transposeChord(item.chord, semitones),
  }));
}

export function transposeKeyLabel(key: string, semitones: number): string {
  if (!key || key === "unknown" || semitones === 0) return key;
  const parts = key.trim().split(/\s+/);
  if (!parts.length) return key;
  const root = normalizeRoot(parts[0]);
  if (!root) return key;
  const idx = NOTES.indexOf(root);
  const newRoot = NOTES[(((idx + semitones) % 12) + 12) % 12];
  const rest = parts.slice(1).join(" ");
  return rest ? `${newRoot} ${rest}` : newRoot;
}
