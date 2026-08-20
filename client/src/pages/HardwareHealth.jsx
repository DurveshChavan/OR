import { useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Cell } from "recharts";
import Card from "../components/Card";
import EditableNumberField from "../components/EditableNumberField";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import { useHardware, useComparison, useAgeHardware, useReplaceHardware } from "../hooks/useHardware";

const STAGE_COLOR = { baseline: "var(--color-data-neutral)", aged: "var(--color-critical)", replaced: "var(--color-good)" };

export default function HardwareHealth() {
  const hardware = useHardware();
  const comparison = useComparison();
  const ageMutation = useAgeHardware();
  const replaceMutation = useReplaceHardware();

  const [months, setMonths] = useState(24);

  if (hardware.isLoading) return <LoadingState label="Reading workstation fleet..." />;
  if (hardware.isError) return <ErrorState error={hardware.error} />;

  const data = hardware.data;
  const toReplaceSet = new Set(data.to_replace);

  const comparisonData = ["baseline", "aged", "replaced"].map((stage) => ({
    stage,
    cost: comparison.data?.[stage] ?? null,
  }));

  const comparisonSummary =
    "Assignment cost by stage: " +
    comparisonData.map((d) => `${d.stage} ${d.cost == null ? "not run yet" : d.cost.toFixed(0)}`).join(", ") + ".";

  return (
    <div className="space-y-4">
      <Card
        eyebrow="Module IV · Replacement theory"
        title="Three-stage comparison"
        subtitle="Baseline -> aged -> replaced assignment cost against the current funded agent pool. Use 'Age' then 'Replace' below to populate all three stages."
        className="order-first"
      >
        <div role="img" aria-label={comparisonSummary}>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={comparisonData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-rule)" />
              <XAxis dataKey="stage" tick={{ fontSize: 12, fill: "var(--color-muted)" }} />
              <YAxis tick={{ fontSize: 12, fill: "var(--color-muted)" }} />
              <Tooltip formatter={(v) => (v == null ? "not run yet" : v.toFixed(0))} contentStyle={{ borderRadius: 6, borderColor: "var(--color-rule-2)", fontSize: 12 }} />
              <Bar dataKey="cost" radius={[2, 2, 0, 0]}>
                {comparisonData.map((d) => (
                  <Cell key={d.stage} fill={STAGE_COLOR[d.stage]} fillOpacity={d.cost == null ? 0.15 : 1} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <div className="flex gap-4 mt-2">
          {Object.entries(STAGE_COLOR).map(([stage, color]) => (
            <span key={stage} className="flex items-center gap-1.5 text-xs text-muted">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} aria-hidden="true" />
              {stage}
            </span>
          ))}
        </div>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <Card title="Age the fleet" subtitle="Adds this many months to every workstation's age, then compares baseline vs aged assignment cost.">
        <div className="flex items-center gap-4">
          <EditableNumberField label="Age +N months" value={months} min={0} onChange={setMonths} />
          <button
            className="rounded-control bg-accent text-accent-ink text-sm font-medium px-4 py-2 hover:brightness-110 transition-[filter] duration-150 ease-out disabled:opacity-50 self-end"
            onClick={() => ageMutation.mutate(months)}
            disabled={ageMutation.isPending}
          >
            {ageMutation.isPending ? "Ageing..." : `Age +${months} months`}
          </button>
        </div>
        {ageMutation.isError && <ErrorState error={ageMutation.error} />}
        {ageMutation.data && (
          <p className="mt-2 text-sm text-ink-2">
            Baseline {ageMutation.data.baseline_cost.toFixed(0)} {"->"} Aged{" "}
            <span className="font-semibold text-critical tabular-nums">{ageMutation.data.aged_cost.toFixed(0)}</span>{" "}
            (+{ageMutation.data.delta.toFixed(0)})
          </p>
        )}
      </Card>

      <Card title="Replacement" subtitle="Resets the flagged workstations' age to 0 and re-compares against the current aged cost.">
        <p className="text-sm text-ink-2 mb-2">
          Flagged for replacement (under at least one plausible degradation-rate assumption):{" "}
          <span className="font-medium text-ink">{data.to_replace.length ? data.to_replace.join(", ") : "none"}</span>
        </p>
        <button
          className="rounded-control bg-accent text-accent-ink text-sm font-medium px-4 py-2 hover:brightness-110 transition-[filter] duration-150 ease-out disabled:opacity-50"
          onClick={() => replaceMutation.mutate(data.to_replace)}
          disabled={replaceMutation.isPending || data.to_replace.length === 0}
        >
          {replaceMutation.isPending ? "Replacing..." : "Replace recommended"}
        </button>
        {replaceMutation.isError && <ErrorState error={replaceMutation.error} />}
        {replaceMutation.data && (
          <p className="mt-2 text-sm text-ink-2">
            Aged {replaceMutation.data.aged_cost.toFixed(0)} {"->"} Replaced{" "}
            <span className="font-semibold text-good tabular-nums">{replaceMutation.data.replaced_cost.toFixed(0)}</span>{" "}
            ({replaceMutation.data.delta.toFixed(0)})
          </p>
        )}
      </Card>
      </div>

      <Card title="Per-workstation degradation factor" subtitle="factor = exp(alpha * age_months); flagged workstations outlined.">
        <div className="space-y-1">
          {data.factors.map((f) => (
            <div key={f.workstation_id} className="flex items-center gap-2 text-xs">
              <span className={`w-16 shrink-0 tabular-nums ${toReplaceSet.has(f.workstation_id) ? "font-semibold text-critical" : "text-ink-2"}`}>
                {f.workstation_id}
              </span>
              <span className="w-14 shrink-0 text-muted">{f.type}</span>
              <div className="flex-1 h-3 bg-paper-2 rounded-control overflow-hidden">
                <div
                  className={toReplaceSet.has(f.workstation_id) ? "bg-critical h-full" : "bg-data-neutral h-full"}
                  style={{ width: `${Math.min(100, ((f.factor - 1) / 1.5) * 100)}%` }}
                />
              </div>
              <span className="w-16 text-right text-ink-2 tabular-nums">{f.factor.toFixed(2)}x</span>
              <span className="w-16 text-right text-muted tabular-nums">{f.age_months.toFixed(0)}mo</span>
            </div>
          ))}
        </div>
      </Card>

      <Card bare title="Sensitivity to the degradation-rate assumption" subtitle="No real hardware-aging dataset exists; this sweeps the assumed rate and shows the recommendation is stable.">
        <table className="text-sm w-full">
          <thead>
            <tr className="text-left font-mono-label text-[0.6875rem] text-muted">
              <th className="py-1.5 font-medium">alpha</th>
              <th className="py-1.5 font-medium text-right">Implied replacement age (months)</th>
              <th className="py-1.5 font-medium text-right">Workstations flagged</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {data.sensitivity.map((row) => (
              <tr key={row.alpha}>
                <td className="py-1.5 text-ink-2 tabular-nums">{row.alpha.toFixed(4)}</td>
                <td className="py-1.5 text-ink-2 tabular-nums text-right">{row.replace_age_months.toFixed(1)}</td>
                <td className="py-1.5 text-ink-2 tabular-nums text-right">{row.n_flagged}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-muted">
          Deteriorating-item optimal replacement year: {data.deteriorating_optimal_year} -- group-vs-individual
          cheaper policy: {data.group_cheaper_policy}
        </p>
        <p className="mt-2 text-xs text-muted">{data.source}</p>
      </Card>
    </div>
  );
}
