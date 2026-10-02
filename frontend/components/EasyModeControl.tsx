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
    <div className="flex items-center gap-3 flex-wrap">
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        onClick={() => onChange(!enabled)}
        className={[
          "font-pixel text-xs px-3 py-2 border-2 border-black transition-all",
          enabled
            ? "bg-lime text-ink shadow-hard-sm"
            : "bg-coal text-paper-dim shadow-hard-sm hover:text-paper",
        ].join(" ")}
      >
        EASY {enabled ? "ON" : "OFF"}
      </button>

      {enabled && (
        <span className="font-cl text-xs text-paper-dim">
          {capo > 0 ? `capo ${capo}` : "no capo"}
          {easyKey ? ` · shapes in ${easyKey}` : ""}
          {reason ? ` · ${reason}` : ""}
        </span>
      )}
    </div>
  );
}
