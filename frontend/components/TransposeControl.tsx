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
  const keyLabel =
    semitones === 0 ? originalKey ?? "?" : transposedKey ?? "?";

  return (
    <div className="h-full flex flex-col gap-2.5">
      <span className="font-cl text-paper-dim text-xs uppercase tracking-[0.2em]">
        Key
      </span>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2.5">
        <div className="flex items-baseline gap-2">
          <span className="font-pixel text-paper text-base sm:text-lg">
            {keyLabel}
          </span>
          {semitones !== 0 && originalKey && (
            <span className="font-cl text-paper-dim text-xs sm:text-sm">
              was {originalKey}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 sm:ml-auto">
          <button
            type="button"
            onClick={() => onChange(Math.max(-11, semitones - 1))}
            disabled={semitones <= -11}
            aria-label="Transpose down one semitone"
            className="w-11 h-11 flex items-center justify-center bg-paper text-ink border-2 border-black shadow-hard-sm font-sans font-bold text-2xl leading-none hover:-translate-y-px active:translate-x-[2px] active:translate-y-[2px] active:shadow-none disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:translate-y-0 transition-transform"
          >
            −
          </button>
          <span
            className="font-pixel text-base text-center w-16 h-11 flex items-center justify-center bg-ink border-2 border-soot select-none"
            aria-live="polite"
            aria-label={`Transpose ${semitones} semitones`}
          >
            {semitones === 0 ? "ORIG" : `${semitones > 0 ? "+" : ""}${semitones}`}
          </span>
          <button
            type="button"
            onClick={() => onChange(Math.min(11, semitones + 1))}
            disabled={semitones >= 11}
            aria-label="Transpose up one semitone"
            className="w-11 h-11 flex items-center justify-center bg-paper text-ink border-2 border-black shadow-hard-sm font-sans font-bold text-2xl leading-none hover:-translate-y-px active:translate-x-[2px] active:translate-y-[2px] active:shadow-none disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:translate-y-0 transition-transform"
          >
            +
          </button>
        </div>
      </div>
    </div>
  );
}
