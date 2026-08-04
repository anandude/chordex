/**
 * easyChords.ts
 * -------------
 * Client-side easy mode — mirrors backend easy_chords.py.
 * Capo + extension stripping without a second API call.
 */

import { transposeChord, transposeKeyLabel } from "./transpose";

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

const EASY_MAJOR = new Set(["C", "G", "D", "A", "E"]);
const EASY_MINOR = new Set(["Am", "Em", "Dm"]);
const EASY_OTHER = new Set([
  "C7",
  "G7",
  "D7",
  "A7",
  "E7",
  "B7",
  "Am7",
  "Em7",
  "Dm7",
  "Asus2",
  "Asus4",
  "Dsus2",
  "Dsus4",
  "Esus4",
  "Cadd9",
  "Gsus4",
]);

const STRIP_RULES: Array<[string, string]> = [
  ["maj13", ""],
  ["maj11", ""],
  ["maj9", ""],
  ["maj7", ""],
  ["m11", "m"],
  ["m13", "m"],
  ["m9", "m"],
  ["m7b5", "m"],
  ["m7", "m"],
  ["min7", "m"],
  ["min", "m"],
  ["dim7", "dim"],
  ["add9", ""],
  ["add11", ""],
  ["sus2", "sus2"],
  ["sus4", "sus4"],
  ["sus", "sus4"],
  ["11", "7"],
  ["13", "7"],
  ["9", "7"],
  ["6", ""],
  ["aug", "aug"],
  ["dim", "dim"],
  ["5", ""],
  ["7", "7"],
  ["m", "m"],
];

function normalizeRoot(raw: string): string | null {
  if (!raw) return null;
  if (raw.length >= 2 && (raw[1] === "#" || raw[1] === "b")) {
    const root = FLAT_TO_SHARP[raw.slice(0, 2)] ?? raw.slice(0, 2);
    return NOTES.includes(root) ? root : null;
  }
  const root = raw[0].toUpperCase();
  return NOTES.includes(root) ? root : null;
}

function parseChord(chord: string): [string, string] {
  if (chord === "N") return ["N", ""];
  let body = chord;
  if (chord.includes("/")) body = chord.split("/")[0];
  if (body.length >= 2 && (body[1] === "#" || body[1] === "b")) {
    const root = FLAT_TO_SHARP[body.slice(0, 2)] ?? body.slice(0, 2);
    return [root, body.slice(2)];
  }
  return [body[0], body.slice(1)];
}

export function simplifyChord(chord: string): string {
  if (!chord || chord === "N") return "N";
  const [root, quality] = parseChord(chord);
  if (!NOTES.includes(root)) return chord;

  let q = quality.replace("major", "maj").replace("minor", "min");
  if (q.startsWith("min") && !q.startsWith("min7")) q = "m" + q.slice(3);
  else if (q.startsWith("min7")) q = "m7" + q.slice(4);

  let simplified = q;
  for (const [token, replacement] of STRIP_RULES) {
    if (q === token) {
      simplified = replacement;
      break;
    }
    if (
      q.startsWith(token) &&
      ["m7", "maj7", "m9", "9", "11", "13", "add9"].includes(token)
    ) {
      simplified = replacement;
      break;
    }
  }
  if (simplified === "maj" || simplified === "M") simplified = "";
  return root + simplified;
}

function shapeDifficulty(chord: string): number {
  if (chord === "N") return 0;
  const simple = simplifyChord(chord);
  const [root, quality] = parseChord(simple);
  const label = root + quality;
  if (EASY_MAJOR.has(label) || EASY_MINOR.has(label) || EASY_OTHER.has(label))
    return 0;
  if (
    ["", "m", "7", "m7", "sus2", "sus4"].includes(quality) &&
    EASY_MAJOR.has(root)
  )
    return 0.2;
  if (
    ["F", "A#", "D#", "G#", "C#"].includes(root) &&
    ["", "m", "7", "m7"].includes(quality)
  )
    return 2.5;
  if (["Bm", "F#m", "C#m", "G#m", "D#m", "F#", "B"].includes(label)) return 2.0;
  return 1.5;
}

function scoreProgression(chords: Array<{ chord: string }>): number {
  if (!chords.length) return 0;
  return (
    chords.reduce((s, c) => s + shapeDifficulty(c.chord), 0) / chords.length
  );
}

export function simplifyProgression<T extends { chord: string }>(
  chords: T[],
  capo = 0
): T[] {
  return chords.map((c) => {
    let chord = c.chord;
    if (capo > 0) chord = transposeChord(chord, -capo);
    return { ...c, chord: simplifyChord(chord) };
  });
}

export interface EasySuggestion {
  capo: number;
  score: number;
  easyKey?: string;
  reason: string;
  chords: Array<{ timestamp: number; chord: string; end?: number; confidence?: number }>;
}

export function applyEasyMode<
  T extends { timestamp: number; chord: string; end?: number; confidence?: number },
>(chords: T[], key?: string, maxCapo = 7): EasySuggestion {
  if (!chords.length) {
    return {
      capo: 0,
      score: 0,
      easyKey: key,
      reason: "No chords to analyse",
      chords: [],
    };
  }

  let bestCapo = 0;
  let bestScore = Infinity;
  let bestShapes: T[] = chords;

  for (let capo = 0; capo <= maxCapo; capo++) {
    const shapes = simplifyProgression(chords, capo);
    let score = scoreProgression(shapes) + capo * 0.02;
    if (score < bestScore) {
      bestScore = score;
      bestCapo = capo;
      bestShapes = shapes;
    }
  }

  const openCount = bestShapes.filter(
    (c) => shapeDifficulty(c.chord) < 0.5
  ).length;

  return {
    capo: bestCapo,
    score: Math.round(bestScore * 1000) / 1000,
    easyKey: key
      ? bestCapo
        ? transposeKeyLabel(key, -bestCapo)
        : key
      : undefined,
    reason: bestCapo
      ? `Capo ${bestCapo}: ${openCount}/${bestShapes.length} shapes are open/easy`
      : "Open position works well — no capo needed",
    chords: bestShapes,
  };
}
