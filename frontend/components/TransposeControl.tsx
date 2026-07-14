interface Props {
  semitones: number;
  onChange: (semitones: number) => void;
  originalKey?: string;
  transposedKey?: string;
}

function semitoneLabel(n: number): string {
  if (n === 0) return "Original key";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n} semitone${Math.abs(n) !== 1 ? "s" : ""}`;
}

export default function TransposeControl({
  semitones,
  onChange,
  originalKey,
  transposedKey,
}: Props) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
        <span className="text-white font-medium text-sm">Transpose</span>
        <span className="text-gray-400 text-sm">{semitoneLabel(semitones)}</span>
      </div>

      {(originalKey || transposedKey) && (
        <p className="text-xs text-gray-500 mb-3">
          {originalKey && (
            <>
              Detected:{" "}
              <span className="text-gray-300">{originalKey}</span>
            </>
          )}
          {semitones !== 0 && transposedKey && (
            <>
              {" "}
              → <span className="text-blue-300">{transposedKey}</span>
            </>
          )}
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          onClick={() => onChange(Math.max(-11, semitones - 1))}
          disabled={semitones <= -11}
          aria-label="Transpose down one semitone"
          className="w-8 h-8 flex items-center justify-center rounded-full bg-gray-800 text-white font-bold text-lg hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          −
        </button>

        <input
          type="range"
          min={-11}
          max={11}
          value={semitones}
          onChange={(e) => onChange(Number(e.target.value))}
          className="flex-1 accent-blue-500 cursor-pointer"
          aria-label="Transpose semitones"
        />

        <button
          onClick={() => onChange(Math.min(11, semitones + 1))}
          disabled={semitones >= 11}
          aria-label="Transpose up one semitone"
          className="w-8 h-8 flex items-center justify-center rounded-full bg-gray-800 text-white font-bold text-lg hover:bg-gray-700 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          +
        </button>
      </div>

      {semitones !== 0 && (
        <button
          onClick={() => onChange(0)}
          className="mt-3 text-xs text-gray-500 hover:text-gray-300 underline transition-colors"
        >
          Reset to original key
        </button>
      )}
    </div>
  );
}
