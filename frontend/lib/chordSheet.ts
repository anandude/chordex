// Builds the playable chord sheet: lyric lines with chord changes anchored
// to the exact word where they strike, chords-only rows for instrumental
// stretches, and section labels for long gaps.

import { ChordEvent, LyricLine, LyricWord } from "./api";

export interface SheetWord {
  word: string;
  timestamp: number;
  end?: number;
  chords: number[]; // indices into the chords array — changes land here
}

export type SheetRow =
  | { kind: "lyric"; timestamp: number; end?: number; words: SheetWord[] }
  | { kind: "chords"; timestamp: number; end?: number; chords: number[] }
  | { kind: "section"; timestamp: number; label: string };

const WORD_GAP = 0.55; // silence that splits lyric lines
const MAX_LINE_WORDS = 12;
const ANCHOR_TOLERANCE = 0.6; // how far before a line/word a chord can sit
const SECTION_GAP = 8; // instrumental stretch worth labeling

export function activeChordIndex(
  chords: Array<{ timestamp: number; end?: number }>,
  time: number
): number | null {
  if (!chords.length) return null;
  for (let i = 0; i < chords.length; i++) {
    const start = chords[i].timestamp;
    const end =
      chords[i].end ??
      (i + 1 < chords.length ? chords[i + 1].timestamp : start + 999);
    if (time >= start && time < end) return i;
  }
  if (time >= chords[chords.length - 1].timestamp) return chords.length - 1;
  return null;
}

export function activeRowIndex(rows: SheetRow[], time: number): number {
  // the active row is the last row that has started
  let active = -1;
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].timestamp <= time) active = i;
    else break;
  }
  return active;
}

interface WordLike {
  word: string;
  timestamp: number;
  end?: number;
}

function groupWordsIntoLines(
  words: WordLike[],
  gap: number,
  maxWords: number
): WordLike[][] {
  const lines: WordLike[][] = [];
  let current: WordLike[] = [];
  for (const w of words) {
    const prev = current[current.length - 1];
    const pause = prev
      ? w.timestamp - (prev.end ?? prev.timestamp)
      : 0;
    if (prev && (pause > gap || current.length >= maxWords)) {
      lines.push(current);
      current = [];
    }
    current.push(w);
  }
  if (current.length) lines.push(current);
  return lines;
}

function lineEnd(words: WordLike[]): number {
  const last = words[words.length - 1];
  return last.end ?? last.timestamp;
}

// chunk a chord-only stretch into rows: break on time gaps or row width
function chunkChords(indices: number[], chords: ChordEvent[]): number[][] {
  const rows: number[][] = [];
  let current: number[] = [];
  for (const i of indices) {
    const prev = current[current.length - 1];
    const prevEnd = prev != null ? chords[prev].end ?? chords[prev].timestamp : 0;
    if (prev != null && (chords[i].timestamp - prevEnd > 4 || current.length >= 8)) {
      rows.push(current);
      current = [];
    }
    current.push(i);
  }
  if (current.length) rows.push(current);
  return rows;
}

export function buildSheet(
  chords: ChordEvent[],
  words?: LyricWord[],
  lines?: LyricLine[]
): SheetRow[] {
  const rows: SheetRow[] = [];
  if (!chords.length) return rows;

  // No word timings at all — a chord-only sheet
  const usableWords: WordLike[] =
    words && words.length
      ? words
      : (lines ?? []).map((l) => ({
          word: l.text,
          timestamp: l.timestamp,
          end: l.end,
        }));
  const pseudoLines = !(words && words.length); // lines as atomic words

  if (!usableWords.length) {
    flushChords(chords.map((_, i) => i), 0, true);
    return rows;
  }

  const wordLines = pseudoLines
    ? usableWords.map((w) => [w])
    : groupWordsIntoLines(usableWords, WORD_GAP, MAX_LINE_WORDS);

  let chordPtr = 0;

  function flushChords(indices: number[], beforeTs: number, leading: boolean) {
    if (!indices.length) return;
    const spanStart = chords[indices[0]].timestamp;
    const gapSpan = beforeTs - spanStart;
    if (gapSpan > SECTION_GAP || (leading && spanStart > SECTION_GAP)) {
      rows.push({
        kind: "section",
        timestamp: Math.max(0, spanStart - 0.01),
        label: leading ? "INTRO" : "INSTRUMENTAL",
      });
    }
    for (const chunk of chunkChords(indices, chords)) {
      rows.push({
        kind: "chords",
        timestamp: chords[chunk[0]].timestamp,
        end: chords[chunk[chunk.length - 1]].end,
        chords: chunk,
      });
    }
  }

  for (let li = 0; li < wordLines.length; li++) {
    const wl = wordLines[li];
    const start = wl[0].timestamp;
    const prevLine = wordLines[li - 1];
    const prevEnd = prevLine ? lineEnd(prevLine) : 0;

    // chords that belong to the instrumental stretch before this line
    const buffer: number[] = [];
    while (
      chordPtr < chords.length &&
      chords[chordPtr].timestamp < start - ANCHOR_TOLERANCE
    ) {
      if (chords[chordPtr].chord !== "N") buffer.push(chordPtr);
      chordPtr++;
    }
    flushChords(buffer, Math.max(prevEnd + 0.8, start - ANCHOR_TOLERANCE), li === 0);

    // anchor in-line chords to their word
    const sheetWords: SheetWord[] = wl.map((w) => ({
      word: w.word,
      timestamp: w.timestamp,
      end: w.end,
      chords: [],
    }));
    while (
      chordPtr < chords.length &&
      chords[chordPtr].timestamp < lineEnd(wl) + ANCHOR_TOLERANCE
    ) {
      const ts = chords[chordPtr].timestamp;
      if (chords[chordPtr].chord !== "N") {
        // first word whose span contains or follows the chord strike
        let anchor = sheetWords.findIndex(
          (w) => (w.end ?? w.timestamp + 0.35) > ts
        );
        if (anchor === -1) anchor = sheetWords.length - 1;
        sheetWords[anchor].chords.push(chordPtr);
      }
      chordPtr++;
    }
    rows.push({
      kind: "lyric",
      timestamp: start,
      end: lineEnd(wl),
      words: sheetWords,
    });
  }

  // trailing instrumental/outro chords
  const tail: number[] = [];
  while (chordPtr < chords.length) {
    if (chords[chordPtr].chord !== "N") tail.push(chordPtr);
    chordPtr++;
  }
  flushChords(tail, Infinity, false);

  return rows;
}
