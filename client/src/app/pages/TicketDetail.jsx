// One ticket, in the order a dispatcher needs it: what state it is in, who it
// should go to and why, whether it is in escalation and how that ends, what
// machine it is about, and then the history.
//
// The complete stored decision and event payloads are all still here. They are
// behind disclosure controls rather than printed beside the buttons, because an
// audit record is something a person goes and reads, not something a screen
// reads aloud over the work.

import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useInvalidateAll, useSession } from "../lib/session";
import { Banner, Empty, Failure, Loading } from "../components/States";
import { PriorityTag, RiskCell, Section, SlaState } from "../components/Bits";
import { Button } from "../components/Motion";
import { formatCost, formatInstant, formatMinutes, slaClock } from "../lib/format";
import {
  ESCALATION_OUTCOMES,
  ESCALATION_TARGETS,
  activitySummary,
  assetVerdict,
  assignmentSummary,
  displayResolverName,
  escalationTargetLabel,
  levelLabel,
  recommendationAction,
  ticketTitle,
  workTypeLabel,
} from "../lib/presentation";
import { eligibleAgents, stalenessReasons } from "../lib/staleness";

const DECISION_EVENTS = ["ASSIGNMENT_RECOMMENDED", "QUEUED_FOR_TRIAGE", "NO_ELIGIBLE_AGENT"];

export default function TicketDetail() {
  const { ticketId } = useParams();
  const { actor, health } = useSession();
  const invalidate = useInvalidateAll();
  const ticket = useQuery({
    queryKey: ["desk", "ticket", ticketId],
    queryFn: () => api.getTicket(ticketId),
  });
  const events = useQuery({
    queryKey: ["desk", "events", ticketId],
    queryFn: () => api.listEvents(ticketId),
  });
  const agents = useQuery({ queryKey: ["desk", "agents"], queryFn: api.listAgents });
  const policies = useQuery({ queryKey: ["desk", "policies"], queryFn: api.listPolicies });

  const latestDecisionId = useMemo(() => {
    const rows = events.data?.events || [];
    for (let index = rows.length - 1; index >= 0; index -= 1) {
      if (DECISION_EVENTS.includes(rows[index].event_type) && rows[index].decision_id) {
        return rows[index].decision_id;
      }
    }
    return null;
  }, [events.data]);
  const decision = useQuery({
    queryKey: ["desk", "decision", latestDecisionId],
    queryFn: () => api.getDecision(latestDecisionId),
    enabled: Boolean(latestDecisionId),
  });
  const recommend = useMutation({
    mutationFn: () => api.recommend([ticketId], "single"),
    onSuccess: () => invalidate(),
  });

  if (ticket.isLoading) return <Loading what="the ticket" />;
  if (ticket.error) {
    return <Failure error={ticket.error} onRetry={() => ticket.refetch()} />;
  }

  const row = ticket.data.ticket;
  const agentList = agents.data?.agents || [];
  const assignee = row.current_assignee_id
    ? displayResolverName(
        agentList.find((one) => one.id === row.current_assignee_id)?.display_name
      )
    : "Unassigned";
  const stale = stalenessReasons({
    decision: decision.data?.decision,
    ticket: row,
    policies: policies.data?.policies,
    agents: agentList,
    health,
  });
  const clock = slaClock(row.sla_due_at);
  const inReview = row.status === "escalation_review";
  const finished = row.status === "resolved" || row.status === "closed";
  const needsRecovery =
    !inReview &&
    !finished &&
    (clock.overdue || (row.priority === 1 && !row.current_assignee_id) || row.risk_probability >= 0.66);

  return (
    <div className="flex flex-col gap-6">
      <header>
        <Link className="text-sm text-accent underline underline-offset-2" to="/">
          Back to queue
        </Link>
        <div className="mt-3 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm text-muted">
              Ticket {row.external_reference || row.id.slice(0, 8)}
            </p>
            <h1 className="mt-0.5 font-display text-2xl text-ink">{ticketTitle(row)}</h1>
          </div>
          <div className="flex items-center gap-2">
            <PriorityTag priority={row.priority} />
            <span className="rounded-[var(--radius-pill)] border border-rule px-2 py-0.5 text-xs text-ink-2">
              {row.status.replace("_", " ")}
            </span>
          </div>
        </div>
        {row.description ? (
          <p className="mt-3 max-w-3xl whitespace-pre-line text-sm text-ink-2">{row.description}</p>
        ) : null}
      </header>

      <dl className="grid border-y border-rule sm:grid-cols-5">
        <Brief label="SLA">
          {finished ? (row.sla_met ? "Met" : "Breached") : <SlaState dueAt={row.sla_due_at} />}
        </Brief>
        <Brief label="Risk"><RiskCell probability={row.risk_probability} /></Brief>
        <Brief label="Owner">{assignee}</Brief>
        <Brief label="Impact / urgency">{levelLabel(row.impact)} / {levelLabel(row.urgency)}</Brief>
        <Brief label="Service group">{workTypeLabel(row.required_skill)}</Brief>
      </dl>

      <Resolution ticket={row} onActed={invalidate} />

      {finished ? null : <Section
        title="Assignment"
        note="Review a stored suggestion before it changes ticket ownership."
        actions={
          <Button
            tone="accent"
            size="sm"
            disabled={recommend.isPending || !health?.models_available}
            onClick={() => recommend.mutate()}
          >
            {recommend.isPending ? "Preparing…" : "Prepare assignment"}
          </Button>
        }
      >
        {recommend.error ? <Failure error={recommend.error} /> : null}
        {events.isLoading ? <Loading what="the ticket history" /> : null}
        {!latestDecisionId && events.data ? (
          <Empty>
            No assignment suggestion is ready. Prepare one when you are ready to
            review the ticket.
          </Empty>
        ) : null}
        {decision.isLoading ? <Loading what="the assignment suggestion" /> : null}
        {decision.error ? <Failure error={decision.error} /> : null}
        {decision.data ? (
          <Recommendation
            detail={decision.data}
            ticket={row}
            agents={agentList}
            stale={stale}
            actor={actor}
            onActed={invalidate}
          />
        ) : null}
      </Section>}

      {inReview ? <LiveReview ticket={row} onActed={invalidate} /> : null}
      {needsRecovery ? <OpenReview ticket={row} onActed={invalidate} /> : null}

      <AssetSection ticket={row} onActed={invalidate} />

      <Section
        title="Activity"
        note="The history is append-only. Clear summaries appear first; the stored record stays one click away."
      >
        {events.error ? (
          <Failure error={events.error} onRetry={() => events.refetch()} />
        ) : null}
        <Timeline events={events.data?.events} />
      </Section>

      <details className="border-t border-rule pt-4 text-sm">
        <summary className="cursor-pointer font-medium text-ink">
          View ticket record
        </summary>
        <dl className="mt-3 grid gap-3 sm:grid-cols-3">
          <Brief label="Category">{row.category || "Not recorded"}</Brief>
          <Brief label="Opened">{formatInstant(row.opened_at)}</Brief>
          <Brief label="Deadline">{formatInstant(row.sla_due_at)}</Brief>
          <Brief label="Resolved">{row.resolved_at ? formatInstant(row.resolved_at) : "Not resolved"}</Brief>
          <Brief label="Last scored">{formatInstant(row.last_scored_at)}</Brief>
          <Brief label="Source">{row.source}</Brief>
          <Brief label="Model version">
            <span className="font-mono text-xs">
              {row.risk_model_version || "Unavailable"}
            </span>
          </Brief>
        </dl>
        <MissingFeatures events={events.data?.events} />
      </details>
    </div>
  );
}

function Recommendation({ detail, ticket, agents, stale, actor, onActed }) {
  const decision = detail.decision;
  const alternatives = detail.candidate_payload?.alternatives || [];
  const chosen = detail.candidate_payload?.chosen;
  const accept = useMutation({
    mutationFn: () => api.acceptDecision(decision.decision_id),
    onSuccess: onActed,
  });
  const action = recommendationAction(decision);
  const acceptable = action.canAccept && stale.length === 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="border-l-2 border-accent bg-paper-2 px-3 py-3">
        <p className="text-xs text-muted">Suggested action</p>
        <p className="mt-1 font-display text-lg text-ink">
          {decision.recommended_agent
            ? displayResolverName(decision.recommended_agent.display_name)
            : "Manual triage required"}
        </p>
        <p className="mt-1 text-sm text-ink-2">{assignmentSummary(decision)}</p>
      </div>

      <dl className="grid gap-3 sm:grid-cols-4">
        <Brief label="Starts in">{formatMinutes(decision.projected_wait_minutes)}</Brief>
        <Brief label="Projected finish">{formatInstant(decision.projected_finish_at)}</Brief>
        <Brief label="Projected lateness">
          {decision.projected_lateness_minutes
            ? formatMinutes(decision.projected_lateness_minutes)
            : "On time"}
        </Brief>
        <Brief label="Risk at decision">
          <RiskCell probability={decision.risk_probability} />
        </Brief>
      </dl>

      {stale.length ? (
        <Banner tone="warning" title="Refresh this suggestion before assigning.">
          <ul className="mt-1 list-disc pl-5">
            {stale.map((reason) => <li key={reason.dimension}>{reason.text}</li>)}
          </ul>
          <p className="mt-2">
            {actor.role === "manager"
              ? "Use Operations to refresh the score, then prepare a new suggestion."
              : "Ask a manager to refresh the score, then prepare a new suggestion."}
          </p>
        </Banner>
      ) : null}

      {accept.error ? <Failure error={accept.error} /> : null}

      <div className="flex flex-wrap items-center gap-3">
        {action.canAccept ? (
          <Button
            tone="accent"
            disabled={!acceptable || accept.isPending}
            onClick={() => accept.mutate()}
          >
            {accept.isPending ? "Assigning…" : action.label}
          </Button>
        ) : (
          <p className="text-sm text-muted">
            No resolver is ready to assign. Review triage or choose an eligible
            resolver below.
          </p>
        )}
        <span className="text-xs text-muted">
          Confirming creates a new audit event. The suggestion itself is unchanged.
        </span>
      </div>

      <OverrideForm
        decisionId={decision.decision_id}
        ticket={ticket}
        agents={agents}
        alternatives={alternatives}
        recommendedId={decision.recommended_agent?.id}
        onActed={onActed}
      />

      <details className="border-t border-rule pt-3 text-sm">
        <summary className="cursor-pointer font-medium text-ink">
          View decision details
        </summary>
        <p className="mt-3 text-sm text-ink-2">
          <span className="font-medium text-ink">Stored reason:</span>{" "}
          {decision.reason || "No reason stored."}
        </p>
        <dl className="mt-3 grid gap-3 sm:grid-cols-3">
          <Brief label="Predicted duration">
            {formatMinutes(decision.predicted_duration_minutes)}
          </Brief>
          <Brief label="Eligible resolvers">{decision.eligible_agent_count}</Brief>
          <Brief label="Candidate cost">
            <span className="font-mono text-xs">{formatCost(chosen?.total_cost)}</span>
          </Brief>
          <Brief label="Decision state">{decision.state}</Brief>
          <Brief label="Policy version">{decision.policy_version}</Brief>
          <Brief label="Written">{formatInstant(decision.created_at)}</Brief>
        </dl>
        <Alternatives alternatives={alternatives} state={decision.state} />
      </details>
    </div>
  );
}

//: What a person can do to a ticket's lifecycle from each status. A ticket in
//: escalation review has no entry: the review closes first (see LiveReview).
const LIFECYCLE_ACTIONS = {
  open: [{ kind: "resolve", label: "Resolve", tone: "accent" }],
  assigned: [{ kind: "resolve", label: "Resolve", tone: "accent" }],
  resolved: [
    { kind: "close", label: "Close", tone: "accent" },
    { kind: "reopen", label: "Reopen" },
  ],
  closed: [{ kind: "reopen", label: "Reopen" }],
};

/** Resolve, close, reopen: each with a note, each an entry in the history. */
function Resolution({ ticket, onActed }) {
  const [note, setNote] = useState("");
  const act = useMutation({
    mutationFn: (kind) => api[`${kind}Ticket`](ticket.id, note.trim()),
    onSuccess: () => {
      setNote("");
      onActed();
    },
  });
  const actions = LIFECYCLE_ACTIONS[ticket.status] || [];
  if (!actions.length) return null;
  const resolving = actions[0].kind === "resolve";

  return (
    <Section
      title="Resolution"
      note={
        resolving
          ? "Resolving stamps the time, records whether the SLA deadline was met, and frees the resolver's slot."
          : "Close confirms the fix. Reopen sends the ticket back to the queue unassigned; its deadline does not move."
      }
    >
      {ticket.resolved_at ? (
        <p className={`mb-3 text-sm ${ticket.sla_met ? "text-good" : "text-critical"}`}>
          Resolved {formatInstant(ticket.resolved_at)},{" "}
          {ticket.sla_met ? "within its SLA deadline." : "after its SLA deadline."}
        </p>
      ) : null}
      <form
        className="max-w-xl"
        onSubmit={(event) => {
          event.preventDefault();
          if (note.trim()) act.mutate(actions[0].kind);
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-ink">
            {resolving ? "What fixed it?" : "Note"}
          </span>
          <textarea
            className="field min-h-20"
            value={note}
            maxLength={2000}
            onChange={(event) => setNote(event.target.value)}
            placeholder={resolving ? "The fix, in a sentence the caller would understand" : "Why you are closing or reopening it"}
            required
          />
        </label>
        {act.error ? <div className="mt-3"><Failure error={act.error} /></div> : null}
        <div className="mt-3 flex flex-wrap gap-2">
          {actions.map((action) => (
            <Button
              key={action.kind}
              type="button"
              tone={action.tone}
              disabled={!note.trim() || act.isPending}
              onClick={() => act.mutate(action.kind)}
            >
              {act.isPending && act.variables === action.kind ? "Saving…" : action.label}
            </Button>
          ))}
        </div>
      </form>
    </Section>
  );
}

/** Escalation, opened: who it is with, since when, and how it ends. */
function LiveReview({ ticket, onActed }) {
  const [note, setNote] = useState("");
  const [outcome, setOutcome] = useState(ESCALATION_OUTCOMES[0].value);
  const close = useMutation({
    mutationFn: () => api.closeEscalationReview(ticket.id, note, outcome),
    onSuccess: () => {
      setNote("");
      onActed();
    },
  });
  const choices = ESCALATION_OUTCOMES.filter(
    (one) => !one.requiresMachine || ticket.machine_id
  );

  return (
    <Section
      title="Escalation review"
      note="A review is an internal hand-off inside this desk. No external L2 queue or vendor system is contacted, and none is claimed."
    >
      <dl className="grid gap-3 border-y border-rule sm:grid-cols-3">
        <Brief label="With">{escalationTargetLabel(ticket.escalation_target)}</Brief>
        <Brief label="Opened">{formatInstant(ticket.escalation_opened_at)}</Brief>
        <Brief label="Ticket state">In review, still counting against its SLA</Brief>
      </dl>

      <form
        className="mt-4 max-w-xl"
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
        <p className="mt-1 text-xs text-muted">
          {ticket.machine_id
            ? "Closing as a reassignment requires the ticket to have a new owner first."
            : "Link the affected machine below to close this review as a hardware replacement. Closing as a reassignment requires a new owner first."}
        </p>
        <label className="mt-3 flex flex-col gap-1 text-sm">
          <span className="font-medium text-ink">Closing note</span>
          <textarea
            className="field min-h-24"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="What happened, and what the ticket needs next"
            required
          />
        </label>
        {close.error ? <div className="mt-3"><Failure error={close.error} /></div> : null}
        <div className="mt-3 flex flex-col gap-2">
          {!note.trim() && (
            <p className="text-xs text-muted">A closing note is required.</p>
          )}
          <div>
            <Button type="submit" tone="accent" disabled={!note.trim() || close.isPending}>
              {close.isPending ? "Closing…" : "Close review"}
            </Button>
          </div>
        </div>
      </form>
    </Section>
  );
}

/** Escalation, not yet opened: the reason and the reviewer it goes to. */
function OpenReview({ ticket, onActed }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [target, setTarget] = useState(ESCALATION_TARGETS[0].value);
  const choices = ESCALATION_TARGETS.filter(
    (one) => !one.requiresMachine || ticket.machine_id
  );
  const chosen = choices.find((one) => one.value === target) || choices[0];
  const start = useMutation({
    // `chosen`, not `target`: if the asset link is removed while this form is
    // open, the replacement route drops out of `choices` and the select falls
    // back. Submitting `target` would then send a route the person cannot see.
    mutationFn: () => api.startEscalationReview(ticket.id, note, chosen.value),
    onSuccess: () => {
      setOpen(false);
      setNote("");
      onActed();
    },
  });

  return (
    <Section
      title="Recovery action"
      note="This ticket needs an ownership or recovery check before it can be left alone."
    >
      {!open ? (
        <Button tone="neutral" onClick={() => setOpen(true)}>
          Open escalation review
        </Button>
      ) : (
        <form
          className="max-w-xl"
          onSubmit={(event) => {
            event.preventDefault();
            if (note.trim()) start.mutate();
          }}
        >
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-ink">Send the review to</span>
            <select
              className="field"
              value={chosen.value}
              onChange={(event) => setTarget(event.target.value)}
            >
              {choices.map((one) => (
                <option key={one.value} value={one.value}>{one.label}</option>
              ))}
            </select>
          </label>
          <p className="mt-1 text-xs text-muted">{chosen.detail}</p>
          {!ticket.machine_id ? (
            <p className="mt-1 text-xs text-muted">
              Link the affected machine below to send this ticket to the
              replacement decision.
            </p>
          ) : null}
          <label className="mt-3 flex flex-col gap-1 text-sm">
            <span className="font-medium text-ink">Reason for review</span>
            <textarea
              className="field min-h-24"
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="What needs review and why"
              required
            />
          </label>
          {start.error ? <div className="mt-3"><Failure error={start.error} /></div> : null}
          <div className="mt-3 flex flex-col gap-2">
            {!note.trim() && (
              <p className="text-xs text-muted">A reason is required to open a review.</p>
            )}
            <div className="flex gap-2">
              <Button type="submit" tone="accent" disabled={!note.trim() || start.isPending}>
                {start.isPending ? "Opening…" : "Open review"}
              </Button>
              <Button type="button" onClick={() => setOpen(false)}>Cancel</Button>
            </div>
          </div>
        </form>
      )}
    </Section>
  );
}

/** The affected machine, what replacement costs say about it, and the link itself. */
function AssetSection({ ticket, onActed }) {
  const machines = useQuery({
    queryKey: ["desk", "machines"],
    queryFn: () => api.listMachines(),
  });
  const advice = useQuery({
    queryKey: ["desk", "machine-advice", ticket.machine_id],
    queryFn: () => api.machineAdvice(ticket.machine_id),
    enabled: Boolean(ticket.machine_id),
  });
  const [machineId, setMachineId] = useState(ticket.machine_id || "");
  useEffect(() => setMachineId(ticket.machine_id || ""), [ticket.machine_id]);
  const link = useMutation({
    mutationFn: () => api.linkTicketMachine(ticket.id, machineId || null),
    onSuccess: onActed,
  });
  const verdict = assetVerdict(advice.data?.advice);

  return (
    <Section
      title="Affected machine"
      note="A ticket is connected to an asset only when a person says so — nothing in the incident data infers it. The link is what lets a review reach the replacement decision; it never changes the assignment."
    >
      {verdict ? (
        <div
          className={
            "border-l-2 px-3 py-3 " +
            (verdict.tone === "critical"
              ? "border-critical bg-critical-soft"
              : verdict.tone === "warning"
              ? "border-risk bg-risk-soft"
              : "border-rule-2 bg-paper-2")
          }
        >
          <p className="font-medium text-ink">{verdict.headline}</p>
          <p className="mt-1 text-sm text-ink-2">{verdict.detail}</p>
          <p className="mt-2 text-xs text-muted">
            Figures are the ones a manager entered in the register.{" "}
            <Link className="underline hover:text-ink" to="/hardware">
              Open asset planning
            </Link>{" "}
            for the year-by-year table.
          </p>
        </div>
      ) : null}

      {machines.isLoading ? <p className="text-sm text-muted">Loading assets…</p> : null}
      {machines.error ? (
        <Failure error={machines.error} onRetry={() => machines.refetch()} />
      ) : null}
      {machines.data ? (
        <form
          className={"flex max-w-xl flex-wrap items-end gap-2 " + (verdict ? "mt-4" : "")}
          onSubmit={(event) => {
            event.preventDefault();
            link.mutate();
          }}
        >
          <label className="min-w-56 flex-1 text-sm">
            <span className="font-medium text-ink">Affected machine</span>
            <select
              className="field mt-1"
              value={machineId}
              onChange={(event) => setMachineId(event.target.value)}
            >
              <option value="">No machine linked</option>
              {machines.data.machines.map((machine) => (
                <option key={machine.id} value={machine.id}>
                  {machine.asset_tag}
                  {machine.location ? ` · ${machine.location}` : ""}
                </option>
              ))}
            </select>
          </label>
          <Button type="submit" disabled={link.isPending}>
            {link.isPending ? "Saving…" : "Save link"}
          </Button>
          {link.error ? <div className="w-full"><Failure error={link.error} /></div> : null}
        </form>
      ) : null}
    </Section>
  );
}

function OverrideForm({ decisionId, ticket, agents, alternatives, recommendedId, onActed }) {
  const priced = new Map((alternatives || []).map((one) => [one.agent_id, one.total_cost]));
  const choices = eligibleAgents(agents, ticket.required_skill).filter(
    (agent) => agent.id !== recommendedId
  );
  const [open, setOpen] = useState(false);
  const [agentId, setAgentId] = useState("");
  const [reason, setReason] = useState("");
  const override = useMutation({
    mutationFn: () => api.overrideDecision(decisionId, agentId, reason),
    onSuccess: () => {
      setReason("");
      setOpen(false);
      onActed();
    },
  });

  if (!open) {
    // `self-start` because the parent is a column flexbox: without it a quiet
    // button with no background stretches and reads as centred body text.
    return (
      <Button
        tone="quiet"
        size="sm"
        className="self-start underline underline-offset-2"
        onClick={() => setOpen(true)}
      >
        Choose another resolver
      </Button>
    );
  }
  return (
    <form
      className="border-t border-rule pt-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (agentId && reason.trim()) override.mutate();
      }}
    >
      <h3 className="font-display text-base text-ink">Choose another resolver</h3>
      <p className="mt-1 text-sm text-muted">
        This leaves the suggestion intact and records why you made a different
        assignment.
      </p>
      {choices.length ? (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-ink">Resolver</span>
            <select
              className="field"
              value={agentId}
              onChange={(event) => setAgentId(event.target.value)}
              required
            >
              <option value="">Choose resolver</option>
              {choices.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {displayResolverName(agent.display_name)}
                  {priced.has(agent.id)
                    ? ` · estimated cost ${formatCost(priced.get(agent.id))}`
                    : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium text-ink">Reason</span>
            <input
              className="field"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Why this resolver is the better choice"
              required
            />
          </label>
        </div>
      ) : (
        <Empty>No other active resolver currently matches the required skill.</Empty>
      )}
      {override.error ? <div className="mt-3"><Failure error={override.error} /></div> : null}
      <div className="mt-3 flex gap-2">
        <Button
          type="submit"
          tone="accent"
          disabled={!agentId || !reason.trim() || override.isPending}
        >
          {override.isPending ? "Assigning…" : "Assign selected resolver"}
        </Button>
        <Button type="button" onClick={() => setOpen(false)}>Cancel</Button>
      </div>
    </form>
  );
}

function Alternatives({ alternatives, state }) {
  if (!alternatives.length) {
    return (
      <p className="mt-3 text-sm text-muted">
        No other resolver was priced for this decision.
      </p>
    );
  }
  return (
    <div className="mt-4">
      <p className="font-medium text-ink">Resolver options considered</p>
      <p className="mt-1 text-xs text-muted">
        State: {state}. These are the stored options at the time of the decision.
      </p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-128 text-sm">
          <thead>
            <tr className="border-b border-rule text-left text-xs text-muted">
              <th className="py-2 pr-2 font-medium">Resolver</th>
              <th className="py-2 pr-2 font-medium">Starts in</th>
              <th className="py-2 pr-2 font-medium">Finish in</th>
              <th className="py-2 font-medium">Cost</th>
            </tr>
          </thead>
          <tbody>
            {alternatives.map((one) => (
              <tr key={one.agent_id} className="border-b border-rule">
                <td className="py-2 pr-2">{displayResolverName(one.display_name)}</td>
                <td className="py-2 pr-2">{formatMinutes(one.projected_wait_minutes)}</td>
                <td className="py-2 pr-2">
                  {formatMinutes(one.projected_finish_in_minutes)}
                </td>
                <td className="py-2 font-mono text-xs">{formatCost(one.total_cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Timeline({ events }) {
  if (!events) return null;
  if (!events.length) return <Empty>No activity has been recorded yet.</Empty>;
  return (
    <ol className="divide-y divide-rule">
      {events.map((event) => {
        const summary = activitySummary(event);
        return (
          <li key={event.id} className="py-3 first:pt-0">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="font-medium text-ink">{summary.title}</h3>
              <time className="text-xs text-muted">{formatInstant(event.occurred_at)}</time>
            </div>
            <p className="mt-1 text-sm text-ink-2">{summary.detail}</p>
            <details className="mt-2 text-xs text-muted">
              <summary className="cursor-pointer">{summary.technicalLabel}</summary>
              <pre className="mt-2 overflow-x-auto rounded bg-paper-2 p-2 font-mono text-ink-2">
                {JSON.stringify(event.payload, null, 2)}
              </pre>
            </details>
          </li>
        );
      })}
    </ol>
  );
}

function MissingFeatures({ events }) {
  const latest = (events || [])
    .filter((event) => event.event_type === "RISK_SCORED")
    .slice(-1)[0];
  const missing = latest?.payload?.unavailable_features;
  return missing?.length ? (
    <p className="mt-3 text-xs text-muted">
      The score was estimated without: {missing.join(", ")}. Read the risk band as
      a review cue, not as a precise forecast.
    </p>
  ) : null;
}

function Brief({ label, children }) {
  return (
    <div className="border-b border-rule px-3 py-3 last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-1 text-sm text-ink">{children}</dd>
    </div>
  );
}
