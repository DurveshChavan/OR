import { useState } from "react";
import Card from "../components/Card";
import Heatmap from "../components/Heatmap";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import { useAssignment } from "../hooks/useAssignment";

export default function TicketAssignment() {
  const [showAged, setShowAged] = useState(false);
  const baseline = useAssignment(false);
  const aged = useAssignment(true, { enabled: showAged });

  if (baseline.isLoading) return <LoadingState label="Solving assignment..." />;
  if (baseline.isError) return <ErrorState error={baseline.error} />;

  const data = baseline.data;
  const highlightCells = new Set(
    data.pairs.map((p) => `${data.ticket_ids.indexOf(p.ticket_id)}-${data.agent_ids.indexOf(p.agent_id)}`)
  );

  let movedTicketIds = [];
  if (showAged && aged.data) {
    const baselineAgentByTicket = Object.fromEntries(data.pairs.map((p) => [p.ticket_id, p.agent_id]));
    const agedAgentByTicket = Object.fromEntries(aged.data.pairs.map((p) => [p.ticket_id, p.agent_id]));
    const allIds = new Set([...Object.keys(baselineAgentByTicket), ...Object.keys(agedAgentByTicket)]);
    movedTicketIds = [...allIds].filter((id) => baselineAgentByTicket[id] !== agedAgentByTicket[id]);
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-4 items-start">
      <Card
        eyebrow="Module III · Hungarian"
        title="Cost matrix"
        subtitle="Rows = tickets, columns = funded agents. Highlighted cells are the Hungarian-optimal choice; blank cells are skill mismatches (infeasible)."
      >
        <Heatmap matrix={data.matrix} rowLabels={data.ticket_ids} colLabels={data.agent_ids} highlightCells={highlightCells} />
        <p className="mt-4 font-display text-2xl font-semibold text-ink tabular-nums">
          {data.total_cost.toFixed(0)} <span className="text-sm font-body font-normal text-muted">minutes</span>
        </p>
        <p className="text-xs text-muted">
          total resolution time across {data.n_tickets_served} served tickets.
        </p>
      </Card>

      <Card title="Hardware impact">
        <label className="flex items-center gap-2 text-sm text-ink-2">
          <input type="checkbox" checked={showAged} onChange={(e) => setShowAged(e.target.checked)} className="accent-accent" />
          Show hardware impact (apply current workstation degradation factors)
        </label>

        {showAged && (
          <div className="mt-3">
            {aged.isLoading && <LoadingState label="Re-solving with degradation..." />}
            {aged.isError && <ErrorState error={aged.error} />}
            {aged.data && (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-control border border-rule p-3">
                    <p className="text-xs text-muted">Baseline total</p>
                    <p className="text-xl font-display font-semibold text-ink tabular-nums">{data.total_cost.toFixed(0)}</p>
                  </div>
                  <div className="rounded-control border border-rule p-3">
                    <p className="text-xs text-muted">Aged total</p>
                    <p
                      className={`text-xl font-display font-semibold tabular-nums ${
                        aged.data.total_cost > data.total_cost ? "text-critical" : "text-ink"
                      }`}
                    >
                      {aged.data.total_cost.toFixed(0)}
                    </p>
                  </div>
                </div>
                <p className="mt-3 text-xs text-muted">
                  {movedTicketIds.length} ticket(s) moved to a different agent (or dropped) once hardware
                  ageing was applied:
                </p>
                <div className="mt-1 flex flex-wrap gap-1">
                  {movedTicketIds.map((id) => (
                    <span key={id} className="inline-block rounded-control bg-risk-soft text-risk text-xs px-2 py-0.5">
                      {id}
                    </span>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
