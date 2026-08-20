import { BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer, Legend, Cell } from "recharts";
import Card from "../components/Card";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import { useSchedule } from "../hooks/useSchedule";
import { useEscalations } from "../hooks/useEscalations";

function breachColor(timeToBreachHours) {
  if (timeToBreachHours == null) return "var(--color-data-neutral)"; // unknown
  if (timeToBreachHours <= 0) return "var(--color-critical)"; // already breaches
  if (timeToBreachHours <= 2) return "var(--color-risk)"; // cutting it close
  return "var(--color-good)"; // comfortably inside the SLA window
}

export default function WorkQueue() {
  const schedule = useSchedule();
  const escalations = useEscalations();

  if (schedule.isLoading) return <LoadingState label="Sequencing the assigned batch..." />;
  if (schedule.isError) return <ErrorState error={schedule.error} />;

  const breachByTicket = Object.fromEntries(
    (escalations.data?.rows ?? []).map((r) => [r.ticket_id, r.time_to_breach_hours])
  );

  const chartData = schedule.data.entries.map((e) => ({
    ticket: e.ticket_id,
    spacer1: e.triage_start,
    triage: e.triage_end - e.triage_start,
    spacer2: Math.max(0, e.fix_start - e.triage_end),
    fix: e.fix_end - e.fix_start,
    completion: e.completion_minutes,
    color: breachColor(breachByTicket[e.ticket_id]),
  }));

  return (
    <div className="space-y-4">
      <Card
        eyebrow="Module III · Johnson's rule"
        title="Sequenced work queue"
        subtitle="Johnson's-rule two-stage flow shop (triage, then fix) over the assigned batch. Bar colour = completion vs SLA deadline (from Escalation Advisor)."
      >
        <div
          role="img"
          aria-label={
            "Sequenced work queue, " + chartData.length + " tickets, completion times: " +
            chartData.map((e) => `${e.ticket} ${e.completion.toFixed(0)} minutes`).join(", ") + "."
          }
        >
          <ResponsiveContainer width="100%" height={Math.max(240, chartData.length * 28)}>
            <BarChart data={chartData} layout="vertical" margin={{ left: 24 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-rule)" />
              <XAxis type="number" tick={{ fontSize: 12, fill: "var(--color-muted)" }} label={{ value: "minutes", position: "insideBottom", offset: -5, fontSize: 11, fill: "var(--color-muted)" }} />
              <YAxis type="category" dataKey="ticket" tick={{ fontSize: 11, fill: "var(--color-muted)" }} width={70} />
              <Tooltip formatter={(v, name) => (name === "spacer1" || name === "spacer2" ? null : [v.toFixed(1), name])} contentStyle={{ borderRadius: 6, borderColor: "var(--color-rule-2)", fontSize: 12 }} />
              <Legend payload={[
                { value: "triage", type: "square", color: "var(--color-data-neutral)" },
                { value: "fix (coloured by SLA)", type: "square", color: "var(--color-good)" },
              ]} />
              <Bar dataKey="spacer1" stackId="a" fill="transparent" />
              <Bar dataKey="triage" stackId="a" fill="var(--color-data-neutral)" />
              <Bar dataKey="spacer2" stackId="a" fill="transparent" />
              <Bar dataKey="fix" stackId="a">
                {chartData.map((entry) => (
                  <Cell key={entry.ticket} fill={entry.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <p className="mt-4 font-display text-2xl font-semibold text-ink tabular-nums">
          {schedule.data.makespan.toFixed(1)} <span className="text-sm font-body font-normal text-muted">min makespan</span>
        </p>
      </Card>

      <Card bare title="Per-ticket completion vs SLA deadline">
        <table className="text-sm w-full">
          <thead>
            <tr className="text-left font-mono-label text-[0.6875rem] text-muted">
              <th className="py-1.5 font-medium">Ticket</th>
              <th className="py-1.5 font-medium text-right">Completion (min)</th>
              <th className="py-1.5 font-medium text-right">Time to breach (h)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rule">
            {chartData.map((row) => (
              <tr key={row.ticket}>
                <td className="py-1.5 text-ink-2">{row.ticket}</td>
                <td className="py-1.5 text-ink-2 tabular-nums text-right">{row.completion.toFixed(1)}</td>
                <td className="py-1.5 tabular-nums text-right font-medium" style={{ color: row.color }}>
                  {breachByTicket[row.ticket] != null ? breachByTicket[row.ticket].toFixed(1) : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
