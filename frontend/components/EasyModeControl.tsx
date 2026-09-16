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
    <div className="h-full flex flex-col gap-2.5">
      <span className="font-cl text-paper-dim text-xs uppercase tracking-[0.2em]">
        Easy mode
      </span>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2.5">
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          onClick={() => onChange(!enabled)}
          className={[
            "min-h-11 font-pixel text-sm px-4 py-2.5 border-2 border-black transition-all",
            enabled
              ? "bg-lime text-ink shadow-hard-sm"
              : "bg-ink/60 text-paper-dim shadow-hard-sm hover:text-paper",
          ].join(" ")}
        >
          EASY {enabled ? "ON" : "OFF"}
        </button>

        {enabled ? (
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1.5">
            <span
              className={`font-pixel text-xs px-2.5 py-1.5 border-2 border-black ${
                capo > 0 ? "bg-gold text-ink" : "bg-soot text-paper-dim"
              }`}
            >
              {capo > 0 ? `CAPO ${capo}` : "NO CAPO"}
            </span>
            {easyKey && (
              <span className="font-cl text-paper-dim text-xs sm:text-sm">
                open shapes in {easyKey}
              </span>
            )}
          </div>
        ) : (
          <span className="font-cl text-paper-dim/80 text-xs sm:text-sm">
            rewrites chords for open shapes
          </span>
        )}
      </div>

      {enabled && reason && (
        <p className="font-cl text-paper-dim/75 text-xs leading-snug">
          {reason}
        </p>
      )}
    </div>
  );
}
