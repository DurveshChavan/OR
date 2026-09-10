// Screen 2 — one ticket, its latest recommendation, and everything that has
// happened to it.
//
// The rule this file exists to keep: the reason a dispatcher reads is the
// reason the decision stored. Nothing here rebuilds that sentence from the
// numbers beside it, and nothing recomputes a cost. The alternatives shown are
// the ones the solve priced and wrote into the decision payload, so what is on
// screen is what the audit trail holds.
//
// There is no endpoint that lists a ticket's decisions, and the contract is
// frozen, so the latest recommendation is found the way the history already
// records it: the newest event carrying a decision id names the decision, and
// that decision is then read by id.

import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useInvalidateAll, useSession } from "../lib/session";
import { Banner, Empty, Failure, Loading } from "../components/States";
import { PriorityTag, RiskCell, Section, SlaState } from "../components/Bits";
import { formatCost, formatInstant, formatMinutes } from "../lib/format";
import { eligibleAgents, stalenessReasons } from "../lib/staleness";

const DECISION_EVENTS = [
  "ASSIGNMENT_RECOMMENDED",
  "QUEUED_FOR_TRIAGE",
  "NO_ELIGIBLE_AGENT",
];

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
      const event = rows[index];
      if (DECISION_EVENTS.includes(event.event_type) && event.decision_id) {
        return event.decision_id;
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
  const stale = stalenessReasons({
    decision: decision.data?.decision,
    ticket: row,
    policies: policies.data?.policies,
    agents: agentList,
    health,
  });

  return (
    <>
      <Section
        title={row.external_reference || row.id}
        note="Deadlines are stored in UTC and shown in this browser's zone."
        actions={
          <Link className="text-sm text-accent underline" to="/">
            Back to the queue
          </Link>
        }
      >
        <dl className="grid gap-3 sm:grid-cols-3">
          <Fact label="status">{row.status}</Fact>
          <Fact label="priority">
            <PriorityTag priority={row.priority} />
          </Fact>
          <Fact label="required skill">{row.required_skill || "—"}</Fact>
          <Fact label="opened">{formatInstant(row.opened_at)}</Fact>
          <Fact label="SLA deadline">
            {formatInstant(row.sla_due_at)} · <SlaState dueAt={row.sla_due_at} />
          </Fact>
          <Fact label="assignee">
            {row.current_assignee_id
              ? agentList.find((one) => one.id === row.current_assignee_id)
                  ?.display_name || "unknown resolver"
              : "unassigned"}
          </Fact>
          <Fact label="latest score">
            <RiskCell
              probability={row.risk_probability}
              modelVersion={row.risk_model_version}
            />
          </Fact>
          <Fact label="last scored">{formatInstant(row.last_scored_at)}</Fact>
          <Fact label="source">{row.source}</Fact>
        </dl>
        <MissingFeatures events={events.data?.events} />
      </Section>

      <Section
        title="Latest recommendation"
        note="One immutable row. Accepting or overriding it adds an event; neither edits it."
        actions={
          <button
            type="button"
            disabled={recommend.isPending || !health?.models_available}
            onClick={() => recommend.mutate()}
            className="rounded-[var(--radius-control)] bg-accent px-3 py-1.5 text-sm text-accent-ink disabled:opacity-50"
          >
            {recommend.isPending ? "Generating…" : "Generate recommendation"}
          </button>
        }
      >
        {recommend.error ? <Failure error={recommend.error} /> : null}
        {events.isLoading ? <Loading what="the history" /> : null}
        {!latestDecisionId && events.data ? (
          <Empty>
            No recommendation has been written for this ticket yet.
          </Empty>
        ) : null}
        {decision.isLoading && latestDecisionId ? (
          <Loading what="the recommendation" />
        ) : null}
        {decision.error ? <Failure error={decision.error} /> : null}
        {decision.data ? (
          <Recommendation
            detail={decision.data}
            ticket={row}
            agents={agentList}
            stale={stale}
            actor={actor}
            onActed={() => invalidate()}
          />
        ) : null}
      </Section>

      <Section title="History" note="Append-only. The database refuses updates and deletes on these rows.">
        {events.error ? (
          <Failure error={events.error} onRetry={() => events.refetch()} />
        ) : null}
        <Timeline events={events.data?.events} />
      </Section>
    </>
  );
}

function Recommendation({ detail, ticket, agents, stale, actor, onActed }) {
  const decision = detail.decision;
  const alternatives = detail.candidate_payload?.alternatives || [];
  const note = detail.candidate_payload?.alternatives_note;
  const chosen = detail.candidate_payload?.chosen;

  const accept = useMutation({
    mutationFn: () => api.acceptDecision(decision.decision_id),
    onSuccess: onActed,
  });

  const acceptable = decision.state === "recommended" && stale.length === 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-[var(--radius-card)] border border-rule bg-paper-2 p-3">
        <p className="font-mono-label text-[10px] text-muted">stored reason</p>
        <p className="mt-1 text-sm text-ink">{decision.reason}</p>
        <p className="mt-2 font-mono-label text-[10px] text-muted">
          decision {decision.decision_id.slice(0, 8)} · state {decision.state} ·
          policy v{decision.policy_version} · model {decision.model_version || "none"} ·
          written {formatInstant(decision.created_at)}
        </p>
      </div>

      <dl className="grid gap-3 sm:grid-cols-4">
        <Fact label="recommended">
          {decision.recommended_agent?.display_name || "no resolver"}
        </Fact>
        <Fact label="projected wait">
          {formatMinutes(decision.projected_wait_minutes)}
        </Fact>
        <Fact label="projected finish">
          {formatInstant(decision.projected_finish_at)}
        </Fact>
        <Fact label="projected lateness">
          {decision.projected_lateness_minutes
            ? formatMinutes(decision.projected_lateness_minutes)
            : "none"}
        </Fact>
        <Fact label="candidate cost">{formatCost(chosen?.total_cost)}</Fact>
        <Fact label="eligible resolvers">{decision.eligible_agent_count}</Fact>
        <Fact label="predicted duration">
          {formatMinutes(decision.predicted_duration_minutes)}
        </Fact>
        <Fact label="risk at decision">
          <RiskCell
            probability={decision.risk_probability}
            modelVersion={decision.model_version}
          />
        </Fact>
      </dl>

      {stale.length ? (
        <Banner tone="warning" title="This recommendation is out of date.">
          <ul className="mt-1 list-disc pl-5">
            {stale.map((reason) => (
              <li key={reason.dimension}>{reason.text}</li>
            ))}
          </ul>
          <p className="mt-2">
            {actor.role === "manager"
              ? "Rescore from the Administration screen, then generate a new recommendation."
              : "Ask a manager to rescore, then generate a new recommendation."}
          </p>
        </Banner>
      ) : null}

      {accept.error ? <Failure error={accept.error} /> : null}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          disabled={!acceptable || accept.isPending}
          onClick={() => accept.mutate()}
          className="rounded-[var(--radius-control)] bg-accent px-4 py-2 text-sm text-accent-ink disabled:opacity-50"
        >
          {accept.isPending ? "Accepting…" : "Accept recommendation"}
        </button>
        {decision.state !== "recommended" ? (
          <span className="text-sm text-muted">
            This decision is a {decision.state} outcome, so there is nothing to
            accept. Override to assign someone by hand.
          </span>
        ) : null}
      </div>

      <Alternatives
        alternatives={alternatives}
        note={note}
        state={decision.state}
      />

      <OverrideForm
        decisionId={decision.decision_id}
        ticket={ticket}
        agents={agents}
        alternatives={alternatives}
        recommendedId={decision.recommended_agent?.id}
        onActed={onActed}
      />
    </div>
  );
}

//: What the list means depends on what the solve decided. For a recommended
//: decision these are the runners-up; for a queued one the solve chose the
//: queue over all of them, and calling them "alternatives" without saying that
//: would suggest a resolver was available and passed over.
const ALTERNATIVES_HEADING = {
  recommended: "other resolvers the solve priced",
  queued: "resolvers the solve priced before choosing the queue",
  no_eligible_agent: "resolvers the solve priced",
};

function Alternatives({ alternatives, note, state }) {
  if (!alternatives.length) {
    return (
      <Empty>
        {state === "no_eligible_agent"
          ? "No resolver holds the required skill, so nothing was priced."
          : "No other eligible resolver was priced for this ticket at that moment."}
      </Empty>
    );
  }
  return (
    <div>
      <p className="font-mono-label text-[10px] text-muted">
        {ALTERNATIVES_HEADING[state] || "resolvers the solve priced"}
      </p>
      {state === "queued" ? (
        <p className="mt-1 text-xs text-muted">
          Every one of these was priced above the queue for this ticket, or its
          slot went to another ticket in the same tier. Overriding to one of
          them is a human decision the solve did not make.
        </p>
      ) : null}
      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[560px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-rule text-left font-mono-label text-[10px] text-muted">
              <th scope="col" className="py-2 pr-2">resolver</th>
              <th scope="col" className="py-2 pr-2">starts in</th>
              <th scope="col" className="py-2 pr-2">finishes in</th>
              <th scope="col" className="py-2 pr-2">lateness</th>
              <th scope="col" className="py-2 pr-2">cost</th>
            </tr>
          </thead>
          <tbody>
            {alternatives.map((one) => (
              <tr key={one.agent_id} className="border-b border-rule">
                <td className="py-2 pr-2">{one.display_name}</td>
                <td className="py-2 pr-2">
                  {formatMinutes(one.projected_wait_minutes)}
                </td>
                <td className="py-2 pr-2">
                  {formatMinutes(one.projected_finish_in_minutes)}
                </td>
                <td className="py-2 pr-2">
                  {one.projected_lateness_minutes
                    ? formatMinutes(one.projected_lateness_minutes)
                    : "none"}
                </td>
                <td className="py-2 pr-2">{formatCost(one.total_cost)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {note ? <p className="mt-2 text-xs text-muted">{note}</p> : null}
    </div>
  );
}

function OverrideForm({
  decisionId,
  ticket,
  agents,
  alternatives,
  recommendedId,
  onActed,
}) {
  // Two sets, and the difference is visible on purpose. The alternatives table
  // above holds resolvers the solve actually priced; this dropdown also lists
  // resolvers who were at their WIP limit when the batch solved and therefore
  // had no column in the cost matrix at all. They are still worth offering -
  // capacity may have freed since - but they carry no cost, and the server
  // re-checks eligibility at submit and can still refuse with
  // AGENT_NOT_ELIGIBLE. Showing one flat list would have implied the solve
  // considered all of them.
  const priced = new Map(
    (alternatives || []).map((one) => [one.agent_id, one.total_cost])
  );
  const choices = eligibleAgents(agents, ticket.required_skill).filter(
    (agent) => agent.id !== recommendedId
  );
  const unpriced = choices.filter((agent) => !priced.has(agent.id));
  const [agentId, setAgentId] = useState("");
  const [reason, setReason] = useState("");
  const override = useMutation({
    mutationFn: () => api.overrideDecision(decisionId, agentId, reason),
    onSuccess: () => {
      setReason("");
      onActed();
    },
  });

  const typed = reason.trim().length > 0;

  return (
    <form
      className="rounded-[var(--radius-card)] border border-rule bg-paper-2 p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (!typed || !agentId) return;
        override.mutate();
      }}
    >
      <p className="font-display text-base text-ink">Override</p>
      <p className="mt-1 text-sm text-muted">
        Assign someone else on the record. The recommendation is not edited; the
        disagreement is stored beside it.
      </p>

      {choices.length === 0 ? (
        <Empty>
          No other active resolver holds the required{" "}
          {ticket.required_skill || "general"} skill. Add the skill on the
          Administration screen first.
        </Empty>
      ) : (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-mono-label text-[11px] text-muted">resolver</span>
            <select
              className="rounded-[var(--radius-control)] border border-rule-2 bg-paper px-3 py-2"
              value={agentId}
              onChange={(event) => setAgentId(event.target.value)}
              required
            >
              <option value="">choose a resolver</option>
              {choices.map((agent) => (
                <option key={agent.id} value={agent.id}>
                  {agent.display_name}
                  {priced.has(agent.id)
                    ? ` — cost ${formatCost(priced.get(agent.id))}`
                    : " — not priced in this solve"}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-mono-label text-[11px] text-muted">
              reason (required)
            </span>
            <input
              className="rounded-[var(--radius-control)] border border-rule-2 bg-paper px-3 py-2"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="why this resolver instead"
              required
            />
          </label>
        </div>
      )}

      {unpriced.length ? (
        <p className="mt-2 text-xs text-muted">
          {unpriced.length} resolver(s) in this list were at their WIP limit when
          the batch solved, so the solve never priced them. They are offered
          because capacity may have freed since; eligibility is re-checked when
          the override is submitted.
        </p>
      ) : null}

      {override.error ? (
        <div className="mt-3">
          <Failure error={override.error} />
        </div>
      ) : null}

      <button
        type="submit"
        disabled={!typed || !agentId || override.isPending}
        className="mt-3 rounded-[var(--radius-control)] border border-accent px-4 py-2 text-sm text-accent disabled:opacity-50"
      >
        {override.isPending ? "Recording…" : "Override and assign"}
      </button>
      {!typed ? (
        <p className="mt-2 text-xs text-muted">
          An override with no written reason is an unexplained change in the
          audit trail, so the button stays disabled until one is typed.
        </p>
      ) : null}
    </form>
  );
}

/** Fields the artifact was trained on that this application does not hold. */
function MissingFeatures({ events }) {
  const latest = (events || [])
    .filter((event) => event.event_type === "RISK_SCORED")
    .slice(-1)[0];
  const missing = latest?.payload?.unavailable_features;
  if (!missing || !missing.length) return null;
  return (
    <p className="mt-3 text-xs text-muted">
      Scored without {missing.join(", ")}: these are fields the model was fitted
      on that this application does not record, so the artifact imputed them.
      Read the score as a band, not as a precise probability.
    </p>
  );
}

function Timeline({ events }) {
  if (!events) return null;
  if (!events.length) return <Empty>No events yet.</Empty>;
  return (
    <ol className="flex flex-col gap-2">
      {events.map((event) => (
        <li
          key={event.id}
          className="rounded-[var(--radius-control)] border border-rule bg-paper-2 p-3"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <span className="font-mono-label text-[11px] text-ink">
              {event.event_type}
            </span>
            <span className="text-xs text-muted">
              {formatInstant(event.occurred_at)}
            </span>
          </div>
          <pre className="mt-2 overflow-x-auto text-xs text-ink-2">
            {JSON.stringify(event.payload, null, 2)}
          </pre>
        </li>
      ))}
    </ol>
  );
}

function Fact({ label, children }) {
  return (
    <div>
      <dt className="font-mono-label text-[10px] text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-ink">{children}</dd>
    </div>
  );
}
