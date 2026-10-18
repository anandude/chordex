// Helpers for the chord sheet. The sheet itself (which word each chord change
// sits on) is built and tested in the backend — backend/pipeline/sheet.py —
// so this file only answers "what is playing now" and exports text.

import { ChordEvent, Sheet, SheetRow, SheetWord } from "./api";

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

/** The active row is the last non-section row that has started. */
export function activeRowIndex(rows: SheetRow[], time: number): number {
  let active = -1;
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].kind === "section") continue;
    if (rows[i].t <= time) active = i;
    else break;
  }
  return active;
}

/** Index of the word being sung in a lyric row (null between words). */
export function activeWordIndex(
  row: SheetRow | undefined,
  time: number
): number | null {
  if (!row || row.kind !== "line") return null;
  for (let i = row.words.length - 1; i >= 0; i--) {
    const w = row.words[i];
    if (time >= w.t) return time < Math.max(w.end, w.t + 0.15) ? i : null;
  }
  return null;
}

/** Chords-only fallback when the backend could not build a sheet. */
export function chordsOnlySheet(chords: ChordEvent[]): Sheet {
  const idx = chords.flatMap((c, i) => (c.chord === "N" ? [] : [i]));
  return {
    version: 1,
    beat: 0.5,
    rows: idx.length
      ? [
          {
            kind: "bars",
            t: chords[idx[0]].timestamp,
            end: chords[idx[idx.length - 1]].end ?? 0,
            chords: idx,
            beats: idx.map(() => 4),
          },
        ]
      : [],
  };
}

/**
 * Labels to actually show: a chord whose displayed label equals the previous
 * displayed chord (e.g. Easy Mode turns C → Cmaj7 → C into C C C) is not a
 * change for the player, so it is hidden. Returns a Set of hidden indices.
 */
export function redundantChords(sheet: Sheet, labels: string[]): Set<number> {
  // chord indices are in time order, so sorting them gives play order
  const shown: number[] = [];
  for (const r of sheet.rows) {
    if (r.kind === "bars") shown.push(...r.chords);
    if (r.kind === "line") {
      r.words.forEach((w) =>
        w.segs.forEach((s) => s.chord !== null && shown.push(s.chord))
      );
      r.gaps.forEach((g) => shown.push(...g.chords));
    }
  }
  shown.sort((a, b) => a - b);
  const hidden = new Set<number>();
  for (let i = 1; i < shown.length; i++) {
    if (labels[shown[i]] === labels[shown[i - 1]]) hidden.add(shown[i]);
  }
  return hidden;
}

/** Romanised text per segment: the backend's syllable-accurate split when
 *  present, else a proportional split of the whole-word romanisation. */
export function romanSegments(word: SheetWord): string[] {
  if (word.roman_segs?.length === word.segs.length) return word.roman_segs;
  const roman = word.roman ?? word.segs.map((s) => s.text).join("");
  const total = word.segs.reduce((n, s) => n + s.text.length, 0) || 1;
  let acc = 0;
  return word.segs.map((s) => {
    const a = Math.round((acc / total) * roman.length);
    acc += s.text.length;
    const b = Math.round((acc / total) * roman.length);
    return roman.slice(a, b);
  });
}

/** ChordPro text (`[G]Wise men [D]say`) for copy/export. `roman` exports the
 *  English-letter lyrics with chords on the same syllables. */
export function sheetToChordPro(
  sheet: Sheet,
  labels: string[],
  header: string[] = [],
  roman = false
): string {
  const hidden = redundantChords(sheet, labels);
  const tag = (c: number) => (hidden.has(c) ? "" : `[${labels[c]}]`);
  const out: string[] = [...header];
  for (const r of sheet.rows) {
    if (r.kind === "section") {
      out.push("", `{comment: ${r.label}}`);
    } else if (r.kind === "bars") {
      out.push(
        r.chords
          .filter((c) => !hidden.has(c))
          .map((c) => `[${labels[c]}]`)
          .join(" ")
      );
    } else {
      const gapsAt = (k: number) =>
        r.gaps
          .filter((g) => g.after_word === k)
          .flatMap((g) => g.chords.map(tag))
          .join("");
      const words = r.words.map((w, k) => {
        const texts = roman && w.roman ? romanSegments(w) : w.segs.map((s) => s.text);
        const body = w.segs
          .map((s, i) => (s.chord !== null ? tag(s.chord) : "") + texts[i])
          .join("");
        const gap = gapsAt(k);
        return gap ? `${body} ${gap}` : body;
      });
      const lead = gapsAt(-1);
      out.push((lead ? `${lead} ` : "") + words.join(" "));
    }
  }
  return out.join("\n").trim() + "\n";
}
