// Generic matrix heatmap: darker cell = larger value (relative to the
// matrix's own max). `highlightCells` is a Set of "row-col" strings drawn
// with a ring, for "these are the chosen cells" use cases.
export default function Heatmap({ matrix, rowLabels, colLabels, highlightCells, cellFormatter }) {
  const flat = matrix.flat().filter((v) => Number.isFinite(v));
  const max = flat.length ? Math.max(...flat) : 1;
  const format = cellFormatter || ((v) => (Number.isFinite(v) ? v.toFixed(0) : "-"));

  return (
    <div className="overflow-x-auto">
      <table className="border-collapse text-xs">
        <thead>
          <tr>
            <th className="p-1" />
            {colLabels.map((label) => (
              <th key={label} className="p-1 font-mono-label text-[0.625rem] text-muted text-center whitespace-nowrap">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, r) => (
            <tr key={rowLabels[r] ?? r}>
              <th className="p-1 font-mono-label text-[0.625rem] text-muted text-right whitespace-nowrap pr-2">
                {rowLabels[r] ?? r}
              </th>
              {row.map((value, c) => {
                const finite = Number.isFinite(value);
                const intensity = finite && max > 0 ? Math.min(value / max, 1) : 0;
                const chosen = highlightCells?.has(`${r}-${c}`);
                return (
                  <td key={c} className={`p-0 ${chosen ? "ring-2 ring-inset ring-accent" : ""}`}>
                    <div
                      className="w-10 h-8 flex items-center justify-center text-[10px] text-ink-2 tabular-nums"
                      style={{
                        backgroundColor: finite
                          ? `color-mix(in oklch, var(--color-accent) ${8 + intensity * 55}%, var(--color-surface))`
                          : "color-mix(in oklch, var(--color-rule) 40%, transparent)",
                      }}
                      title={finite ? String(value) : "infeasible"}
                    >
                      {finite ? format(value) : "—"}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
