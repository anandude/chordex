interface Props {
  semitones: number;
  onChange: (semitones: number) => void;
  originalKey?: string;
  transposedKey?: string;
}

export default function TransposeControl({
  semitones,
  onChange,
  originalKey,
  transposedKey,
}: Props) {
  return (
    <div className="flex items-center gap-3 flex-wrap">
      <div className="flex items-center gap-2">
        <span className="font-cl text-[10px] uppercase tracking-[0.2em] text-paper-dim">
          Key
        </span>
        <span className="font-pixel text-sm text-paper">
          {semitones === 0 ? originalKey ?? "?" : transposedKey ?? "?"}
        </span>
        {semitones !== 0 && originalKey && (
          <span className="font-cl text-[11px] text-paper-dim/85">
            (was {originalKey})
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => onChange(Math.max(-11, semitones - 1))}
          disabled={semitones <= -11}
          aria-label="Transpose down one semitone"
          className="w-8 h-8 flex items-center justify-center bg-paper text-ink border-2 border-black shadow-hard-sm font-pixel text-lg leading-none pb-0.5 hover:-translate-y-px active:translate-x-[2px] active:translate-y-[2px] active:shadow-none disabled:opacity-30 disabled:cursor-not-allowed transition-transform"
        >
          −
        </button>
        <span
          className="font-pixel text-xs text-center w-[4.5rem] py-1.5 bg-ink border-2 border-soot select-none"
          aria-live="polite"
        >
          {semitones === 0 ? "ORIG" : `${semitones > 0 ? "+" : ""}${semitones}`}
        </span>
        <button
          type="button"
          onClick={() => onChange(Math.min(11, semitones + 1))}
          disabled={semitones >= 11}
          aria-label="Transpose up one semitone"
          className="w-8 h-8 flex items-center justify-center bg-paper text-ink border-2 border-black shadow-hard-sm font-pixel text-lg leading-none pb-0.5 hover:-translate-y-px active:translate-x-[2px] active:translate-y-[2px] active:shadow-none disabled:opacity-30 disabled:cursor-not-allowed transition-transform"
        >
          +
        </button>
      </div>
    </div>
  );
}
