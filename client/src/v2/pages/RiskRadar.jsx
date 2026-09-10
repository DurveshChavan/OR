// Screen 3 — Risk Radar.
//
// The four groups are the point of the screen. Showing one list sorted by risk
// would put the model in charge of what a dispatcher looks at next; splitting
// the list says plainly that a breached ticket still needs a person whatever
// the score says, and that P1 waiting is a capacity fact rather than a model
// output. The server returns the rows already ordered and carries the numbers
// that produced the order, so the grouping here reads them and does not
// recompute urgency.

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { v2 } from "../lib/api";
import { useInvalidateV2 } from "../lib/session";
import { Empty, Failure, Loading } from "../components/States";
import { PriorityTag, RiskCell, Section, SlaState } from "../components/Bits";
import { formatCost, formatMinutes, riskBand } from "../lib/format";

export default function RiskRadar() {
  const radar = useQuery({
    queryKey: ["v2", "radar"],
    queryFn: () => v2.riskRadar({ limit: 200 }),
  });

  const groups = useMemo(() => split(radar.data?.tickets || []), [radar.data]);

  if (radar.isLoading) return <Loading what="the radar" />;
  if (radar.error) {
    return <Failure error={radar.error} onRetry={() => radar.refetch()} />;
  }

  return (
    <>
      <Section
        title="Risk Radar"
        note="Four separate lists, not one ranking. A ticket appears in exactly one of them, in the order the server returned."
      >
        <p className="text-xs text-muted">
          Read at {new Date(radar.data.as_of).toLocaleString()} ·{" "}
          {radar.data.tickets.length} open ticket(s).
        </p>
      </Section>

      <Group
        title="Already overdue — recovery"
        note="Past the deadline. These cannot be starved by fresher work: their urgency rate grows with how late they already are."
        rows={groups.overdue}
      />
      <Group
        title="P1 waiting"
        note="Priority 1 and not yet assigned. Capacity is reserved for these before P2 to P4 are dispatched."
        rows={groups.p1Waiting}
      />
      <Group
        title="High model risk"
        note="Calibrated SLA-risk estimate in the high band. This is a review aid: the replay found no measurable throughput gain from the risk score, and the score is not a claim about any resolver."
        rows={groups.highRisk}
      />
      <Group
        title="Normal queue"
        note="Everything else that is open."
        rows={groups.normal}
      />
    </>
  );
}

/** One ticket lands in one list, checked in this order. */
function split(rows) {
  const overdue = [];
  const p1Waiting = [];
  const highRisk = [];
  const normal = [];
  rows.forEach((row) => {
    if (row.overdue) overdue.push(row);
    else if (row.priority === 1 && !row.current_assignee_id) p1Waiting.push(row);
    else if (riskBand(row.risk_probability) === "high") highRisk.push(row);
    else normal.push(row);
  });
  return { overdue, p1Waiting, highRisk, normal };
}

function Group({ title, note, rows }) {
  return (
    <Section title={`${title} (${rows.length})`} note={note}>
      {rows.length === 0 ? (
        <Empty>Nothing in this group right now.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-rule text-left font-mono-label text-[10px] text-muted">
                <th scope="col" className="py-2 pr-2">reference</th>
                <th scope="col" className="py-2 pr-2">priority</th>
                <th scope="col" className="py-2 pr-2">skill</th>
                <th scope="col" className="py-2 pr-2">SLA</th>
                <th scope="col" className="py-2 pr-2">risk</th>
                <th scope="col" className="py-2 pr-2">urgency / min</th>
                <th scope="col" className="py-2 pr-2">acknowledge</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <RadarRow key={row.ticket_id} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

function RadarRow({ row }) {
  const invalidate = useInvalidateV2();
  const [note, setNote] = useState("");
  const [open, setOpen] = useState(false);
  const acknowledge = useMutation({
    mutationFn: () => v2.acknowledgeEscalation(row.ticket_id, note),
    onSuccess: () => {
      setOpen(false);
      setNote("");
      invalidate();
    },
  });

  return (
    <>
      <tr className="border-b border-rule align-top">
        <td className="py-2 pr-2">
          <Link className="text-accent underline" to={`/v2/tickets/${row.ticket_id}`}>
            {row.external_reference || row.ticket_id.slice(0, 8)}
          </Link>
          <div className="text-[11px] text-muted">{row.status}</div>
        </td>
        <td className="py-2 pr-2">
          <PriorityTag priority={row.priority} />
        </td>
        <td className="py-2 pr-2">{row.required_skill || "—"}</td>
        <td className="py-2 pr-2">
          <SlaState dueAt={row.sla_due_at} />
          {row.overdue ? (
            <div className="text-[11px] text-muted">
              {formatMinutes(row.overdue_minutes)} past due
            </div>
          ) : null}
        </td>
        <td className="py-2 pr-2">
          <RiskCell
            probability={row.risk_probability}
            modelVersion={row.risk_model_version}
          />
        </td>
        <td className="py-2 pr-2">{formatCost(row.urgency_cost_per_minute)}</td>
        <td className="py-2 pr-2">
          <button
            type="button"
            onClick={() => setOpen((current) => !current)}
            className="rounded-[var(--radius-control)] border border-rule-2 px-2 py-1 text-xs"
            aria-expanded={open}
          >
            {open ? "Cancel" : "Acknowledge"}
          </button>
        </td>
      </tr>
      {open ? (
        <tr className="border-b border-rule bg-paper-2">
          <td colSpan={7} className="p-3">
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (!note.trim()) return;
                acknowledge.mutate();
              }}
            >
              <label className="flex min-w-[280px] flex-1 flex-col gap-1 text-sm">
                <span className="font-mono-label text-[11px] text-muted">
                  note (required)
                </span>
                <input
                  className="rounded-[var(--radius-control)] border border-rule-2 bg-paper px-3 py-2"
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder="what you decided and why"
                  required
                />
              </label>
              <button
                type="submit"
                disabled={!note.trim() || acknowledge.isPending}
                className="rounded-[var(--radius-control)] border border-accent px-3 py-2 text-sm text-accent disabled:opacity-50"
              >
                {acknowledge.isPending ? "Recording…" : "Record acknowledgement"}
              </button>
              <p className="w-full text-xs text-muted">
                This appends one immutable event. It does not change the status,
                the assignee or the deadline, and it routes nothing to a vendor
                or to L2 — a person decides what happens next.
              </p>
              {acknowledge.error ? (
                <div className="w-full">
                  <Failure error={acknowledge.error} />
                </div>
              ) : null}
            </form>
          </td>
        </tr>
      ) : null}
    </>
  );
}
