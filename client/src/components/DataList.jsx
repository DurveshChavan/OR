// Label : value rows for simple read-only results — a typographic
// alternative to a <table> for the two-column case, so results don't all
// read as "yet another data table" the way a boxed <thead>/<tbody> does.
export default function DataList({ rows, valueClassName = "" }) {
  return (
    <dl className="divide-y divide-rule">
      {rows.map(({ label, value, flag }) => (
        <div key={label} className="flex items-baseline justify-between gap-4 py-2">
          <dt className="text-sm text-ink-2">{label}</dt>
          <dd
            className={`font-display font-semibold tabular-nums ${
              flag === "critical" ? "text-critical" : flag === "good" ? "text-good" : "text-ink"
            } ${valueClassName || "text-sm"}`}
          >
            {value}
          </dd>
        </div>
      ))}
    </dl>
  );
}
