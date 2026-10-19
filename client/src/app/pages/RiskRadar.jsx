// At risk — the escalation half of the product.
//
// One ordered list, not four competing tables, and every row ends in an action
// that changes the ticket: confirm an owner, open a review with a named
// reviewer, or close a review that is already running. A row whose only control
// records that somebody looked at it is the thing this screen used to be.
//
// The list is deliberately shorter than the queue. It holds work that is
// overdue, unowned at P1, scored high, or already in review — nothing else, so
// that an empty screen means there is nothing to chase rather than that a
// filter is hiding it.

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useInvalidateAll } from "../lib/session";
import { Empty, Failure, Loading } from "../components/States";
import { PriorityTag, RiskCell, Section, SlaState } from "../components/Bits";
import { Button } from "../components/Motion";
import {
  ESCALATION_OUTCOMES,
  ESCALATION_TARGETS,
  atRiskAction,
  escalationTargetLabel,
  workTypeLabel,
} from "../lib/presentation";
import { riskBand } from "../lib/format";

const FILTERS = [
  ["all", "All work"],
  ["overdue", "Overdue"],
  ["assignment", "Needs owner"],
  ["review", "Needs review"],
  ["in-review", "In review"],
];

function needsOwner(row) {
  return row.priority === 1 && !row.current_assignee_id;
}

function needsReview(row) {
  return riskBand(row.risk_probability) === "high";
}

export default function RiskRadar() {
  const [filter, setFilter] = useState("all");
  const radar = useQuery({
    queryKey: ["desk", "radar"],
    queryFn: () => api.riskRadar({ limit: 200 }),
  });

  const rows = radar.data?.tickets || [];
  const actionable = useMemo(
    () =>
      rows.filter(
        (row) =>
          row.overdue || needsOwner(row) || needsReview(row) || row.status === "escalation_review"
      ),
    [rows]
  );
  const visible = useMemo(
    () =>
      actionable.filter((row) => {
        if (filter === "in-review") return row.status === "escalation_review";
        if (row.status === "escalation_review") return filter === "all";
        if (filter === "overdue") return row.overdue;
        if (filter === "assignment") return needsOwner(row);
        if (filter === "review") return needsReview(row);
        return true;
      }),
    [actionable, filter]
  );
  const summary = useMemo(
    () => ({
      overdue: rows.filter((row) => row.overdue).length,
      owner: rows.filter((row) => row.priority === 1 && !row.current_assignee_id)
        .length,
      review: rows.filter((row) => row.status === "escalation_review").length,
    }),
    [rows]
  );

  if (radar.isLoading) return <Loading what="at-risk tickets" />;
  if (radar.error) {
    return <Failure error={radar.error} onRetry={() => radar.refetch()} />;
  }

  return (
    <div className="flex flex-col gap-6">
      <header>
        <p className="text-sm text-muted">SLA risk and escalation</p>
        <h1 className="mt-0.5 font-display text-2xl text-ink">At risk</h1>
        <p className="mt-1 max-w-2xl text-sm text-ink-2">
          Start with overdue work and unowned P1 tickets. Escalating opens a
          review with a named reviewer inside this desk, and every review is
          closed with a stated outcome.
        </p>
      </header>

      <dl className="grid border-y border-rule sm:grid-cols-3">
        <Summary label="Overdue" value={summary.overdue} />
        <Summary label="P1 without owner" value={summary.owner} />
        <Summary label="In escalation review" value={summary.review} />
      </dl>

      <Section
        title="Action queue"
        note="Ordered by P1, overdue work, urgency, then SLA deadline. Risk supports the review decision; it never assigns a resolver on its own."
        actions={
          <div className="flex flex-wrap gap-1" role="group" aria-label="At-risk filters">
            {FILTERS.map(([value, label]) => (
              <Button
                key={value}
                tone={filter === value ? "accent" : "quiet"}
                size="sm"
                aria-pressed={filter === value}
                onClick={() => setFilter(value)}
              >
                {label}
              </Button>
            ))}
          </div>
        }
      >
        {visible.length === 0 ? (
          <Empty>No tickets match this view.</Empty>
        ) : (
          <>
            <DesktopRows rows={visible} />
            <MobileRows rows={visible} />
          </>
        )}
      </Section>
    </div>
  );
}

function Summary({ label, value }) {
  return (
    <div className="flex items-baseline justify-between border-b border-rule px-3 py-3 last:border-b-0 sm:block sm:border-b-0 sm:border-r sm:last:border-r-0">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="mt-0 font-display text-2xl text-ink sm:mt-1">{value}</dd>
    </div>
  );
}

function TicketCell({ row }) {
  return (
    <>
      <Link
        className="font-medium text-accent underline underline-offset-2"
        to={`/tickets/${row.ticket_id}`}
      >
        {row.external_reference || row.ticket_id.slice(0, 8)}
      </Link>
      <p className="mt-0.5 text-xs text-muted">
        <PriorityTag priority={row.priority} /> · {workTypeLabel(row.required_skill)}
        {row.status === "escalation_review" ? (
          <>
            {" "}
            · <span className="text-risk">
              in review with the {escalationTargetLabel(row.escalation_target).toLowerCase()}
            </span>
          </>
        ) : null}
      </p>
    </>
  );
}

function DesktopRows({ rows }) {
  return (
    <div className="mt-2 hidden lg:block">
      <table className="w-full text-sm">
        <caption className="sr-only">Tickets that need SLA attention</caption>
        <thead>
          <tr className="border-b border-rule text-left text-xs text-muted">
            <th scope="col" className="py-2 pr-3 font-medium">Ticket</th>
            <th scope="col" className="py-2 pr-3 font-medium">SLA</th>
            <th scope="col" className="py-2 pr-3 font-medium">Risk</th>
            <th scope="col" className="py-2 pr-3 font-medium">Owner</th>
            <th scope="col" className="py-2 font-medium">Next action</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.ticket_id} className="border-b border-rule align-top">
              <td className="py-3 pr-3"><TicketCell row={row} /></td>
              <td className="py-3 pr-3"><SlaState dueAt={row.sla_due_at} /></td>
              <td className="py-3 pr-3"><RiskCell probability={row.risk_probability} /></td>
              <td className="py-3 pr-3">
                {row.current_assignee_id ? "Assigned" : "Unassigned"}
              </td>
              <td className="py-3"><RowAction row={row} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MobileRows({ rows }) {
  return (
    <ul className="mt-2 divide-y divide-rule lg:hidden">
      {rows.map((row) => (
        <li key={row.ticket_id} className="py-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0"><TicketCell row={row} /></div>
            <RiskCell probability={row.risk_probability} />
          </div>
          <div className="mt-3 flex flex-wrap items-start justify-between gap-3">
            <SlaState dueAt={row.sla_due_at} />
            <RowAction row={row} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** One row, one next action, and it always changes something. */
function RowAction({ row }) {
  const action = atRiskAction(row);
  if (action.kind === "close") return <CloseReview row={row} action={action} />;
  if (action.kind === "assign") {
    return (
      <Link
        className="text-sm font-medium text-accent underline underline-offset-2"
        to={`/tickets/${row.ticket_id}`}
      >
        {action.label}
      </Link>
    );
  }
  return <StartReview row={row} action={action} />;
}

function StartReview({ row, action }) {
  const invalidate = useInvalidateAll();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [target, setTarget] = useState(ESCALATION_TARGETS[0].value);
  const start = useMutation({
    mutationFn: () => api.startEscalationReview(row.ticket_id, note, target),
    onSuccess: () => {
      setOpen(false);
      setNote("");
      invalidate();
    },
  });

  // The replacement route needs the ticket-to-asset link, and the radar row
  // does not carry one. Rather than offering a choice the server will refuse,
  // that route is reached from the ticket, where the link can be made.
  const choices = ESCALATION_TARGETS.filter((one) => !one.requiresMachine);
  const chosen = choices.find((one) => one.value === target) || choices[0];

  if (!open) {
    return (
      <Button tone="neutral" size="sm" onClick={() => setOpen(true)}>
        {action.label}
      </Button>
    );
  }
  return (
    <form
      className="min-w-64 max-w-sm border-l-2 border-risk pl-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (note.trim()) start.mutate();
      }}
    >
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-ink">Send the review to</span>
        <select
          className="field"
          value={target}
          onChange={(event) => setTarget(event.target.value)}
        >
          {choices.map((one) => (
            <option key={one.value} value={one.value}>{one.label}</option>
          ))}
        </select>
      </label>
      <p className="mt-1 text-xs text-muted">{chosen.detail}</p>
      <label className="mt-2 flex flex-col gap-1 text-sm">
        <span className="font-medium text-ink">Review note</span>
        <input
          className="field"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="What should the review cover?"
          required
        />
      </label>
      {start.error ? <div className="mt-2"><Failure error={start.error} /></div> : null}
      <div className="mt-2 flex flex-col gap-2">
        {!note.trim() ? (
          <p className="text-xs text-muted">A review note is required.</p>
        ) : null}
        <div className="flex gap-2">
          <Button
            tone="accent"
            size="sm"
            type="submit"
            disabled={!note.trim() || start.isPending}
          >
            {start.isPending ? "Opening…" : "Open review"}
          </Button>
          <Button size="sm" type="button" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </div>
      </div>
    </form>
  );
}

function CloseReview({ row, action }) {
  const invalidate = useInvalidateAll();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [outcome, setOutcome] = useState(ESCALATION_OUTCOMES[0].value);
  const close = useMutation({
    mutationFn: () => api.closeEscalationReview(row.ticket_id, note, outcome),
    onSuccess: () => {
      setOpen(false);
      setNote("");
      invalidate();
    },
  });

  // "A hardware replacement was raised" is only offered where a machine is
  // linked, and the radar row does not know. Closing with that outcome is done
  // on the ticket, beside the asset it is about.
  const choices = ESCALATION_OUTCOMES.filter((one) => !one.requiresMachine);

  if (!open) {
    return (
      <div>
        <Button tone="neutral" size="sm" onClick={() => setOpen(true)}>
          {action.label}
        </Button>
        <p className="mt-1 max-w-56 text-xs text-muted">{action.detail}</p>
      </div>
    );
  }
  return (
    <form
      className="min-w-64 max-w-sm border-l-2 border-risk pl-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (note.trim()) close.mutate();
      }}
    >
      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium text-ink">What did the review decide?</span>
        <select
          className="field"
          value={outcome}
          onChange={(event) => setOutcome(event.target.value)}
        >
          {choices.map((one) => (
            <option key={one.value} value={one.value}>{one.label}</option>
          ))}
        </select>
      </label>
      <label className="mt-2 flex flex-col gap-1 text-sm">
        <span className="font-medium text-ink">Closing note</span>
        <input
          className="field"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="What happened, in one line"
          required
        />
      </label>
      <p className="mt-1 text-xs text-muted">
        Closing returns the ticket to the working queue and records the outcome.
      </p>
      {close.error ? <div className="mt-2"><Failure error={close.error} /></div> : null}
      <div className="mt-2 flex flex-col gap-2">
        {!note.trim() ? (
          <p className="text-xs text-muted">A closing note is required.</p>
        ) : null}
        <div className="flex gap-2">
          <Button
            tone="accent"
            size="sm"
            type="submit"
            disabled={!note.trim() || close.isPending}
          >
            {close.isPending ? "Closing…" : "Close review"}
          </Button>
          <Button size="sm" type="button" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </div>
      </div>
    </form>
  );
}
