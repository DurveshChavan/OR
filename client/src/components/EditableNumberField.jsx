export default function EditableNumberField({ label, value, onChange, min, step = 1, suffix }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      <span>{label}</span>
      <div className="flex items-center gap-1">
        <input
          type="number"
          className="w-full rounded-control border border-rule-2 bg-surface px-2 py-1 text-sm text-ink tabular-nums focus:outline-none focus:ring-1 focus:ring-focus focus:border-focus"
          value={value}
          min={min}
          step={step}
          onChange={(e) => onChange(Number(e.target.value))}
        />
        {suffix && <span className="text-muted">{suffix}</span>}
      </div>
    </label>
  );
}
