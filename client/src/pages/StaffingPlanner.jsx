import { useEffect, useState } from "react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, Legend, CartesianGrid, ResponsiveContainer } from "recharts";
import Card from "../components/Card";
import DataList from "../components/DataList";
import EditableNumberField from "../components/EditableNumberField";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import { useStaffing, useResolveStaffing } from "../hooks/useStaffing";

export default function StaffingPlanner() {
  const { data, isLoading, isError, error } = useStaffing();
  const resolve = useResolveStaffing();

  const [budget, setBudget] = useState(null);
  const [costBySkill, setCostBySkill] = useState(null);

  // seed the editable form from the server's current assumptions the
  // first time they arrive -- never from a guessed default.
  useEffect(() => {
    if (data && budget === null) {
      setBudget(data.budget);
      setCostBySkill(data.cost_by_skill);
    }
  }, [data, budget]);

  if (isLoading) return <LoadingState label="Solving staffing plan..." />;
  if (isError) return <ErrorState error={error} />;

  const demandChartData = Object.entries(data.demand_by_skill).map(([skill, demand]) => ({
    skill,
    demand,
    funded: data.agents_per_skill[skill] ?? 0,
  }));

  const infeasible = data.status !== "Optimal";

  const chartSummary =
    "Demand vs funded agents by skill: " +
    demandChartData.map((d) => `${d.skill} ${d.demand} vs ${d.funded}`).join(", ") + ".";

  function resolveNow() {
    resolve.mutate({ budget, cost_by_skill: costBySkill });
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-4 items-start">
        <Card eyebrow="Module I · LPP" title="Demand vs funded headcount per skill" subtitle="Demand is derived from real UCI-498 category volumes (see Overview); funded headcount is this page's LP result.">
          <div role="img" aria-label={chartSummary}>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={demandChartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-rule)" />
                <XAxis dataKey="skill" tick={{ fontSize: 12, fill: "var(--color-muted)" }} />
                <YAxis tick={{ fontSize: 12, fill: "var(--color-muted)" }} />
                <Tooltip contentStyle={{ borderRadius: 6, borderColor: "var(--color-rule-2)", fontSize: 12 }} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar dataKey="demand" fill="var(--color-data-neutral)" name="Demand (tickets)" radius={[2, 2, 0, 0]} />
                <Bar dataKey="funded" fill="var(--color-accent)" name="Funded agents" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card bare title="Funded headcount result">
          <p className="font-display text-3xl font-semibold text-ink tabular-nums">
            {data.total_cost?.toFixed(0) ?? "-"}
          </p>
          <p className="text-xs text-muted mb-3">total staffing cost -- {data.source}</p>
          <DataList
            rows={Object.entries(data.agents_per_skill).map(([skill, count]) => ({
              label: skill,
              value: count,
            }))}
            valueClassName="text-base"
          />
        </Card>
      </div>

      {infeasible && (
        <div className="rounded-control border border-risk/30 bg-risk-soft text-risk text-sm p-3">
          Status: <span className="font-semibold">{data.status}</span> -- the budget can't cover the
          minimum/coverage constraints for every skill. Raise the budget or lower per-skill cost below.
        </div>
      )}

      <Card eyebrow="Editable" title="Editable assumptions" subtitle="Cost per agent and total budget are business policy, not data -- change them and re-solve.">
        {costBySkill && (
          <div className="space-y-3">
            <EditableNumberField label="Budget" value={budget} step={10} onChange={setBudget} />
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
              {Object.entries(costBySkill).map(([skill, cost]) => (
                <EditableNumberField
                  key={skill}
                  label={`Cost / agent (${skill})`}
                  value={cost}
                  step={5}
                  onChange={(v) => setCostBySkill((c) => ({ ...c, [skill]: v }))}
                />
              ))}
            </div>
            <button
              className="rounded-control bg-accent text-accent-ink text-sm font-medium px-4 py-2 hover:brightness-110 transition-[filter] duration-150 ease-out disabled:opacity-50"
              onClick={resolveNow}
              disabled={resolve.isPending}
            >
              {resolve.isPending ? "Re-solving..." : "Re-solve staffing"}
            </button>
            {resolve.isError && <ErrorState error={resolve.error} />}
          </div>
        )}
      </Card>
    </div>
  );
}
