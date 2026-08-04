interface Props {
  enabled: boolean;
  onChange: (enabled: boolean) => void;
  capo: number;
  reason?: string;
  easyKey?: string;
}

export default function EasyModeControl({
  enabled,
  onChange,
  capo,
  reason,
  easyKey,
}: Props) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="text-white font-medium text-sm">Easy chords</p>
          <p className="text-xs text-gray-500 mt-0.5">
            Open shapes + capo suggestion for beginners
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          onClick={() => onChange(!enabled)}
          className={[
            "relative w-12 h-7 rounded-full transition-colors",
            enabled ? "bg-emerald-600" : "bg-gray-700",
          ].join(" ")}
        >
          <span
            className={[
              "absolute top-0.5 left-0.5 w-6 h-6 rounded-full bg-white transition-transform",
              enabled ? "translate-x-5" : "translate-x-0",
            ].join(" ")}
          />
        </button>
      </div>

      {enabled && (
        <div className="mt-3 pt-3 border-t border-gray-800 space-y-1">
          <p className="text-sm text-emerald-300 font-medium">
            {capo > 0 ? `Capo on fret ${capo}` : "No capo needed"}
            {easyKey ? (
              <span className="text-gray-400 font-normal">
                {" "}
                · shapes in {easyKey}
              </span>
            ) : null}
          </p>
          {reason && <p className="text-xs text-gray-500">{reason}</p>}
          <p className="text-[11px] text-gray-600">
            Chord cards show the shapes you play. Sounding pitch matches the
            original song when capo is used.
          </p>
        </div>
      )}
    </div>
  );
}
