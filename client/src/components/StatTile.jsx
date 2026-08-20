// A number is not a document panel. Deliberately NOT a Card (no border, no
// surface fill) so a row of these reads as a stat strip, not another stack
// of identical bordered boxes.
export default function StatTile({ label, value, accent = false }) {
  return (
    <div className="border-b-2 border-rule-2 pb-2">
      <p className="font-mono-label text-[0.625rem] text-muted">{label}</p>
      <p className={`font-display text-2xl font-semibold tabular-nums ${accent ? "text-accent" : "text-ink"}`}>
        {value}
      </p>
    </div>
  );
}
