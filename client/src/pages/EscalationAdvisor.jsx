import { Fragment, useState } from "react";
import Card from "../components/Card";
import StatusBadge from "../components/StatusBadge";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import { useEscalations, useEscalationGame } from "../hooks/useEscalations";

const ACT_LABEL = {
  "resolve-in-place": "Resolve",
  "escalate-L2": "Escalate L2",
  "escalate-vendor": "Vendor",
};

export default function EscalationAdvisor() {
  const { data, isLoading, isError, error } = useEscalations();
  const game = useEscalationGame();
  const [openTicket, setOpenTicket] = useState(null);

  if (isLoading) return <LoadingState label="Routing escalation decisions..." />;
  if (isError) return <ErrorState error={error} />;

  return (
    <div className="space-y-4">
      <Card bare eyebrow="Module II · Decision theory" title="Decisions per act">
        <div className="flex gap-4">
          {Object.entries(data.counts).map(([act, count]) => (
            <div key={act} className="flex items-center gap-2">
              <StatusBadge act={act} />
              <span className="text-sm font-semibold text-ink tabular-nums">{count}</span>
            </div>
          ))}
        </div>
        {data.vendor_cost > 0 && (
          <p className="mt-2 text-xs text-muted">Vendor cost carried: {data.vendor_cost.toFixed(0)}</p>
        )}
      </Card>

      <Card bare title="At-risk tickets" subtitle="Click a row for the expected-cost payoff behind its recommendation.">
        <table className="text-sm w-full">
          <thead>
            <tr className="text-left font-mono-label text-[0.6875rem] text-muted">
              <th className="py-1">Ticket</th>
              <th className="py-1">Priority</th>
              <th className="py-1">Time to breach (h)</th>
              <th className="py-1">Recommendation</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <Fragment key={row.ticket_id}>
                <tr
                  className="border-t border-rule cursor-pointer hover:bg-paper-2 transition-colors duration-150 ease-out"
                  onClick={() => setOpenTicket(openTicket === row.ticket_id ? null : row.ticket_id)}
                >
                  <td className="py-1 text-ink-2">{row.ticket_id}</td>
                  <td className="py-1 text-ink-2">P{row.priority}</td>
                  <td className="py-1 text-ink-2 tabular-nums">
                    {row.time_to_breach_hours != null ? row.time_to_breach_hours.toFixed(1) : "-"}
                  </td>
                  <td className="py-1">
                    <StatusBadge act={row.act} />
                    {row.forced_by_incident_risk && (
                      <span className="ml-2 text-xs text-risk">(forced by incident risk)</span>
                    )}
                  </td>
                </tr>
                {openTicket === row.ticket_id && (
                  <tr className="bg-paper-2">
                    <td colSpan={4} className="p-3">
                      <p className="text-xs text-muted mb-2">
                        Expected cost per act (negative payoff = expected cost; p(breach) already
                        reflects the schedule and any breach-reduction from escalating):
                      </p>
                      <table className="text-xs">
                        <thead>
                          <tr className="text-left font-mono-label text-[0.625rem] text-muted">
                            <th className="pr-4">Act</th>
                            <th className="pr-4">p(breach)</th>
                            <th className="pr-4">Payoff (breach, no-breach)</th>
                            <th>Expected value</th>
                          </tr>
                        </thead>
                        <tbody>
                          {row.acts.map((act, i) => (
                            <tr key={act} className={act === row.act ? "font-semibold text-ink" : "text-muted"}>
                              <td className="pr-4">{ACT_LABEL[act] || act}</td>
                              <td className="pr-4 tabular-nums">{row.p_breach[i].toFixed(2)}</td>
                              <td className="pr-4 tabular-nums">
                                ({row.payoff[i][0].toFixed(0)}, {row.payoff[i][1].toFixed(0)})
                              </td>
                              <td className="tabular-nums">{row.values[i].toFixed(1)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </Card>

      <Card
        eyebrow="Module II · Game theory"
        title="Desk vs. workload (game theory)"
        subtitle="Worst-case guarantee, distribution-free: the desk picks a dispatch strategy not knowing which priority will dominate incoming volume, modelled as a zero-sum game against that uncertainty."
      >
        {game.isLoading && <p className="text-xs text-muted">Solving...</p>}
        {game.isError && <ErrorState error={game.error} />}
        {game.data && (
          <>
            <table className="text-xs mb-2">
              <thead>
                <tr className="text-left font-mono-label text-[0.625rem] text-muted">
                  <th className="pr-3 py-1">Act \ Priority</th>
                  {game.data.priorities.map((p) => (
                    <th key={p} className="pr-3 py-1">P{p}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {game.data.matrix.map((row, i) => (
                  <tr key={game.data.acts[i]} className="border-t border-rule">
                    <td className="pr-3 py-1 text-ink-2">{ACT_LABEL[game.data.acts[i]] || game.data.acts[i]}</td>
                    {row.map((v, j) => (
                      <td
                        key={j}
                        className={`pr-3 py-1 tabular-nums ${
                          game.data.saddle_point.exists &&
                          game.data.saddle_point.position[0] === i &&
                          game.data.saddle_point.position[1] === j
                            ? "font-semibold text-ink"
                            : "text-muted"
                        }`}
                      >
                        {v.toFixed(0)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {game.data.saddle_point.exists ? (
              <p className="text-xs text-ink-2">
                Saddle point at ({ACT_LABEL[game.data.acts[game.data.saddle_point.position[0]]]}, P
                {game.data.priorities[game.data.saddle_point.position[1]]}) -- pure strategy is
                optimal, guaranteed value {game.data.saddle_point.value.toFixed(0)}.
              </p>
            ) : (
              <p className="text-xs text-ink-2">
                No pure equilibrium -- mix {ACT_LABEL[game.data.acts[0]]}{" "}
                {(game.data.graphical.p * 100).toFixed(0)}% / {ACT_LABEL[game.data.acts[1]]}{" "}
                {(100 - game.data.graphical.p * 100).toFixed(0)}%, guaranteed value{" "}
                {game.data.graphical.value.toFixed(0)}.
              </p>
            )}
            <p className="text-xs text-muted mt-1">
              Cross-checked via mixed-strategy LP: value {game.data.mixed_strategy_lp.value.toFixed(0)}
              {game.data.dominance.rows_kept.length < game.data.acts.length ||
              game.data.dominance.cols_kept.length < game.data.priorities.length
                ? " -- dominance eliminated one or more dominated strategies before solving."
                : "."}
            </p>
          </>
        )}
      </Card>
    </div>
  );
}
