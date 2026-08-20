// Small grid of <input type=number> cells backing a 2D matrix, e.g. a
// routing-cost matrix the user is allowed to override before re-solving.
export default function EditableMatrixField({ matrix, rowLabels, colLabels, onChange }) {
  function setCell(r, c, v) {
    const next = matrix.map((row) => [...row]);
    next[r][c] = v;
    onChange(next);
  }

  return (
    <div className="overflow-x-auto">
      <table className="border-collapse text-xs">
        <thead>
          <tr>
            <th className="p-1" />
            {colLabels.map((label) => (
              <th key={label} className="p-1 font-mono-label text-[0.625rem] text-muted text-center">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, r) => (
            <tr key={rowLabels[r] ?? r}>
              <th className="p-1 font-mono-label text-[0.625rem] text-muted text-right pr-2 whitespace-nowrap">
                {rowLabels[r] ?? r}
              </th>
              {row.map((value, c) => (
                <td key={c} className="p-0.5">
                  <input
                    type="number"
                    className="w-14 rounded-control border border-rule-2 bg-surface px-1 py-1 text-center text-xs text-ink tabular-nums focus:outline-none focus:ring-1 focus:ring-focus focus:border-focus"
                    value={value}
                    onChange={(e) => setCell(r, c, Number(e.target.value))}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
