// The dispatcher workbench. A recommendation is deliberately separate from an
// assignment: the queue produces a reviewable suggestion and the ticket page
// records the human acceptance or override.

import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useInvalidateAll, useSession } from "../lib/session";
import { Empty, Failure, Loading } from "../components/States";
import { PriorityTag, RiskCell, Section, SlaState } from "../components/Bits";
import { Button } from "../components/Motion";
import { LEVELS, displayResolverName, recommendationAction, slaPreview, ticketTitle, workTypeLabel } from "../lib/presentation";
import { slaClock } from "../lib/format";

const DISPATCHABLE_STATUSES = ["open", "assigned"];
//: The queue opens on work still to do, as a support queue should; resolved and
//: closed tickets are one filter away rather than mixed in by default.
const FINISHED_STATUSES = ["resolved", "closed"];

//: The SLA filter, and the one definition of "due soon" the queue uses. Two
//: hours is a declared working convention, not a measurement, which is why it
//: is a named constant rather than a number buried in a comparison.
const DUE_SOON_MINUTES = 120;
const SLA_FILTERS = [
  ["", "Any SLA state"],
  ["overdue", "Overdue"],
  ["due-soon", "Due within 2h"],
  ["on-track", "On track"],
];

export function slaBucket(dueAt, now = Date.now()) {
  const clock = slaClock(dueAt, now);
  if (clock.minutes === null) return "on-track";
  if (clock.overdue) return "overdue";
  return clock.minutes <= DUE_SOON_MINUTES ? "due-soon" : "on-track";
}
export default function Queue() {
  const { health } = useSession();
  const invalidate = useInvalidateAll();
  const [selected, setSelected] = useState(() => new Set());
  const [statusFilter, setStatusFilter] = useState("active");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [slaFilter, setSlaFilter] = useState("");
  const [search, setSearch] = useState("");
  // Typing should not fire one request per keystroke ahead of the list it replaces.
  const query = useDeferredValue(search.trim());

  const tickets = useQuery({
    queryKey: ["desk", "tickets", statusFilter, priorityFilter, query],
    queryFn: () => api.listTickets({
      status: statusFilter === "active" ? "" : statusFilter,
      priority: priorityFilter,
      q: query,
      limit: 200,
    }),
  });
  const agents = useQuery({ queryKey: ["desk", "agents"], queryFn: api.listAgents });
  const recommend = useMutation({
    mutationFn: (ticketIds) => api.recommend(ticketIds, ticketIds.length > 1 ? "batch" : "single"),
    onSuccess: () => invalidate(),
  });

  // Auto-assign is the same solve the preview runs, followed by accepting each
  // suggestion the solver was able to make. It is a convenience over two steps
  // a dispatcher can already do one at a time, not a second decision path: the
  // same decision rows are written, and each acceptance is its own audit event
  // against the signed-in user. Anything the solver could not place - queued
  // for triage, or no eligible resolver - is left alone and reported.
  const autoAssign = useMutation({
    mutationFn: async (ticketIds) => {
      const solved = await api.recommend(ticketIds, ticketIds.length > 1 ? "batch" : "single");
      const decisions = solved.decisions || [];
      const assignable = decisions.filter(
        (one) => one.state === "recommended" && one.recommended_agent
      );
      const assigned = [];
      const failed = [];
      for (const decision of assignable) {
        try {
          await api.acceptDecision(decision.decision_id);
          assigned.push(decision);
        } catch (failure) {
          failed.push({ decision, failure });
        }
      }
      return { decisions, assigned, failed, skipped: decisions.length - assignable.length };
    },
    onSuccess: () => invalidate(),
  });

  const allRows = tickets.data?.tickets || [];
  const rows = useMemo(
    () =>
      allRows
        .filter((row) => statusFilter !== "active" || !FINISHED_STATUSES.includes(row.status))
        .filter((row) => !slaFilter || slaBucket(row.sla_due_at) === slaFilter),
    [allRows, statusFilter, slaFilter]
  );
  const dispatchable = rows.filter((row) => DISPATCHABLE_STATUSES.includes(row.status));
  const references = useMemo(
    () => new Map(allRows.map((row) => [row.id, row.external_reference || row.id.slice(0, 8)])),
    [allRows]
  );
  const agentNames = useMemo(
    () => new Map((agents.data?.agents || []).map((agent) => [agent.id, displayResolverName(agent.display_name)])),
    [agents.data]
  );

  function toggle(ticketId) {
    setSelected((current) => {
      const next = new Set(current);
      next.has(ticketId) ? next.delete(ticketId) : next.add(ticketId);
      return next;
    });
  }

  function selectDispatchable() {
    setSelected((current) =>
      current.size === dispatchable.length ? new Set() : new Set(dispatchable.map((row) => row.id))
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-muted">Predictive ticket allocation</p>
          <h1 className="font-display text-2xl text-ink">Work queue</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            Review work by deadline, confirm the suggested resolver, and leave a reason when you choose another path.
          </p>
        </div>
        <NewTicket onCreated={() => { invalidate(); tickets.refetch(); }} />
      </header>

      <QueueSummary rows={rows} />

      <Section
        title="Tickets"
        note="Ordered by SLA deadline. Previewing assignments creates suggestions only; it does not assign a resolver."
      >
        <div
          className="mb-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4"
          role="group"
          aria-label="Queue filters"
        >
          <label className="flex flex-col gap-1 text-sm" htmlFor="queue-search">
            <span className="text-muted">Search</span>
            <input
              id="queue-search"
              type="search"
              className="field text-sm"
              placeholder="Reference or title"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm" htmlFor="queue-status">
            <span className="text-muted">Status</span>
            <select
              id="queue-status"
              className="field text-sm"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
            >
              <option value="active">Active (not resolved or closed)</option>
              <option value="">All statuses</option>
              {["open", "assigned", "escalation_review", "resolved", "closed"].map((status) => (
                <option key={status} value={status}>{status.replace("_", " ")}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm" htmlFor="queue-priority">
            <span className="text-muted">Priority</span>
            <select
              id="queue-priority"
              className="field text-sm"
              value={priorityFilter}
              onChange={(event) => setPriorityFilter(event.target.value)}
            >
              <option value="">All priorities</option>
              {[1, 2, 3, 4].map((priority) => <option key={priority} value={priority}>P{priority}</option>)}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm" htmlFor="queue-sla">
            <span className="text-muted">SLA state</span>
            <select
              id="queue-sla"
              className="field text-sm"
              value={slaFilter}
              onChange={(event) => setSlaFilter(event.target.value)}
            >
              {SLA_FILTERS.map(([value, label]) => (
                <option key={value || "any"} value={value}>{label}</option>
              ))}
            </select>
          </label>
        </div>

        {tickets.isLoading ? <Loading what="the queue" /> : null}
        {tickets.error ? <Failure error={tickets.error} onRetry={() => tickets.refetch()} /> : null}
        {tickets.data && rows.length === 0 ? <Empty>No tickets match these filters.</Empty> : null}

        {rows.length ? (
          <>
            <div className="mt-1 flex flex-wrap items-center justify-between gap-2 border-b border-rule pb-3 text-sm">
              <p className="text-muted">
                {selected.size} selected of {dispatchable.length} dispatchable ticket{dispatchable.length === 1 ? "" : "s"}
              </p>
              <div className="flex flex-wrap gap-2">
                <Button tone="quiet" size="sm" onClick={selectDispatchable}>
                  {selected.size === dispatchable.length ? "Clear selection" : "Select dispatchable"}
                </Button>
                <Button
                  size="sm"
                  disabled={selected.size === 0 || recommend.isPending || autoAssign.isPending || !health?.models_available}
                  onClick={() => recommend.mutate([...selected])}
                >
                  {recommend.isPending ? "Preparing suggestions…" : `Preview assignments (${selected.size})`}
                </Button>
                <Button
                  tone="accent"
                  size="sm"
                  disabled={selected.size === 0 || recommend.isPending || autoAssign.isPending || !health?.models_available}
                  onClick={() => autoAssign.mutate([...selected])}
                >
                  {autoAssign.isPending ? "Assigning…" : `Auto-assign (${selected.size})`}
                </Button>
              </div>
            </div>

            <p className="mt-2 text-xs text-muted">
              Auto-assign solves and confirms in one step, matching each ticket to
              the qualified resolver whose measured speed on that skill and next
              free slot finish it soonest. Preview does the same solve and stops
              before assigning anyone.
            </p>

            {recommend.error ? <div className="mt-3"><Failure error={recommend.error} /></div> : null}
            {autoAssign.error ? <div className="mt-3"><Failure error={autoAssign.error} /></div> : null}
            {autoAssign.data ? <AutoAssignResult result={autoAssign.data} references={references} /> : null}
            {recommend.data ? <AssignmentReview decisions={recommend.data.decisions} references={references} onFinished={() => { invalidate(); tickets.refetch(); }} /> : null}
            <DesktopQueue rows={rows} selected={selected} toggle={toggle} agentNames={agentNames} />
            <MobileQueue rows={rows} selected={selected} toggle={toggle} agentNames={agentNames} />
          </>
        ) : null}
      </Section>
    </div>
  );
}

function QueueSummary({ rows }) {
  const summary = useMemo(() => {
    const live = rows.filter((row) => DISPATCHABLE_STATUSES.includes(row.status));
    const overdue = live.filter((row) => slaBucket(row.sla_due_at) === "overdue").length;
    const dueSoon = live.filter((row) => slaBucket(row.sla_due_at) === "due-soon").length;
    const unassigned = live.filter((row) => !row.current_assignee_id).length;
    return [
      { label: "Overdue", value: overdue },
      { label: "Due within 2h", value: dueSoon },
      { label: "Unassigned", value: unassigned },
      { label: "Open", value: live.length },
    ];
  }, [rows]);
  return (
    <dl className="grid border-y border-rule sm:grid-cols-4">
      {summary.map((item) => (
        <div key={item.label} className="flex items-baseline justify-between border-b border-rule px-3 py-3 last:border-b-0 sm:block sm:border-b-0 sm:border-r sm:last:border-r-0">
          <dt className="text-sm text-muted">{item.label}</dt>
          <dd className="mt-0 font-display text-2xl text-ink sm:mt-1">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function DesktopQueue({ rows, selected, toggle, agentNames }) {
  return (
    <div className="mt-3 hidden overflow-x-auto lg:block">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">Tickets awaiting service-desk action</caption>
        <thead>
          <tr className="border-b border-rule text-left text-xs text-muted">
            <th scope="col" className="w-8 py-2 pr-2">Select</th>
            <th scope="col" className="py-2 pr-3">Ticket</th>
            <th scope="col" className="py-2 pr-3">SLA</th>
            <th scope="col" className="py-2 pr-3">Risk</th>
            <th scope="col" className="py-2 pr-3">Owner</th>
            <th scope="col" className="py-2">Action</th>
          </tr>
        </thead>
        <tbody>{rows.map((ticket) => <QueueTableRow key={ticket.id} ticket={ticket} selected={selected} toggle={toggle} agentNames={agentNames} />)}</tbody>
      </table>
    </div>
  );
}

function QueueTableRow({ ticket, selected, toggle, agentNames }) {
  const canDispatch = DISPATCHABLE_STATUSES.includes(ticket.status);
  return (
    <tr className="border-b border-rule align-middle">
      <td className="py-3 pr-2"><input type="checkbox" aria-label={`Select ${ticket.external_reference || ticket.id}`} disabled={!canDispatch} checked={selected.has(ticket.id)} onChange={() => toggle(ticket.id)} /></td>
      <td className="py-3 pr-3"><Link className="font-medium text-accent underline underline-offset-2" to={`/tickets/${ticket.id}`}>{ticket.external_reference || ticket.id.slice(0, 8)}</Link><p className="mt-0.5 max-w-md truncate text-ink-2" title={ticketTitle(ticket)}>{ticketTitle(ticket)}</p><div className="mt-0.5 flex gap-2 text-xs text-muted"><PriorityTag priority={ticket.priority} /><span>{workTypeLabel(ticket.required_skill)}</span><span>{ticket.status.replace("_", " ")}</span></div></td>
      <td className="py-3 pr-3"><SlaCell ticket={ticket} /></td>
      <td className="py-3 pr-3"><RiskCell probability={ticket.risk_probability} /></td>
      <td className="py-3 pr-3">{ticket.current_assignee_id ? agentNames.get(ticket.current_assignee_id) || "Resolver unavailable" : "Unassigned"}</td>
      <td className="py-3"><Link className="text-accent underline underline-offset-2" to={`/tickets/${ticket.id}`}>Review</Link></td>
    </tr>
  );
}

/** A resolved ticket's SLA is decided; the clock only runs on live work. */
function SlaCell({ ticket }) {
  if (!ticket.resolved_at) return <SlaState dueAt={ticket.sla_due_at} />;
  return ticket.sla_met
    ? <span className="text-good">SLA met</span>
    : <span className="text-critical">SLA breached</span>;
}

function MobileQueue({ rows, selected, toggle, agentNames }) {
  return (
    <ul className="mt-3 divide-y divide-rule lg:hidden">
      {rows.map((ticket) => {
        const canDispatch = DISPATCHABLE_STATUSES.includes(ticket.status);
        return (
          <li key={ticket.id} className="py-3">
            <div className="flex gap-3">
              <input type="checkbox" className="mt-1" aria-label={`Select ${ticket.external_reference || ticket.id}`} disabled={!canDispatch} checked={selected.has(ticket.id)} onChange={() => toggle(ticket.id)} />
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-3"><div><Link className="font-medium text-accent underline underline-offset-2" to={`/tickets/${ticket.id}`}>{ticket.external_reference || ticket.id.slice(0, 8)}</Link><p className="mt-0.5 text-sm text-ink-2">{ticketTitle(ticket)}</p><p className="mt-0.5 text-xs text-muted"><PriorityTag priority={ticket.priority} /> · {workTypeLabel(ticket.required_skill)} · {ticket.status.replace("_", " ")}</p></div><Link className="shrink-0 text-sm text-accent underline underline-offset-2" to={`/tickets/${ticket.id}`}>Review</Link></div>
                <dl className="mt-3 grid grid-cols-3 gap-2 text-xs"><div><dt className="text-muted">SLA</dt><dd className="mt-1"><SlaCell ticket={ticket} /></dd></div><div><dt className="text-muted">Risk</dt><dd className="mt-1"><RiskCell probability={ticket.risk_probability} /></dd></div><div><dt className="text-muted">Owner</dt><dd className="mt-1 text-ink-2">{ticket.current_assignee_id ? agentNames.get(ticket.current_assignee_id) || "Unavailable" : "Unassigned"}</dd></div></dl>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** What auto-assign actually did, including what it refused to do. */
function AutoAssignResult({ result, references }) {
  return (
    <section
      className="mt-4 border-y border-good/30 bg-good-soft/50 px-3 py-3"
      role="status"
      aria-live="polite"
    >
      <h3 className="font-display text-base text-ink">
        {result.assigned.length} ticket{result.assigned.length === 1 ? "" : "s"} assigned
      </h3>
      {result.assigned.length ? (
        <ul className="mt-2 grid gap-1 text-sm text-ink-2 sm:grid-cols-2">
          {result.assigned.map((decision) => (
            <li key={decision.decision_id}>
              <Link
                className="text-accent underline underline-offset-2"
                to={`/tickets/${decision.ticket_id}`}
              >
                {references.get(decision.ticket_id) || decision.ticket_id.slice(0, 8)}
              </Link>{" "}
              to {displayResolverName(decision.recommended_agent?.display_name)}
            </li>
          ))}
        </ul>
      ) : null}
      {result.skipped ? (
        <p className="mt-2 text-sm text-muted">
          {result.skipped} left unassigned: the solver had no eligible resolver
          free for them, and they stay in the queue for triage.
        </p>
      ) : null}
      {result.failed.length ? (
        <p className="mt-2 text-sm text-critical">
          {result.failed.length} could not be confirmed. Open them individually to
          see why.
        </p>
      ) : null}
    </section>
  );
}

function AssignmentReview({ decisions, references, onFinished }) {
  return (
    <section className="mt-4 border-y border-accent/30 bg-accent-soft/40 py-3" aria-labelledby="assignment-preview-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2 px-3"><div><h3 id="assignment-preview-title" className="font-display text-base text-ink">Assignment preview</h3><p className="mt-0.5 text-sm text-muted">Confirm each suggestion individually. A different choice requires a reason on the ticket.</p></div><span className="text-sm text-muted">{decisions.length} suggestion{decisions.length === 1 ? "" : "s"}</span></div>
      <ul className="mt-3 divide-y divide-accent/20 border-y border-accent/20 bg-surface">{decisions.map((decision) => <DecisionPreview key={decision.decision_id} decision={decision} references={references} onFinished={onFinished} />)}</ul>
    </section>
  );
}

function DecisionPreview({ decision, references, onFinished }) {
  const invalidate = useInvalidateAll();
  const accept = useMutation({ mutationFn: () => api.acceptDecision(decision.decision_id), onSuccess: () => { invalidate(); onFinished(); } });
  const action = recommendationAction(decision);
  const ticketLabel = references?.get(decision.ticket_id) || decision.ticket_id?.slice(0, 8) || "Ticket";
  return (
    <li className="flex flex-wrap items-center justify-between gap-3 px-3 py-3"><div><Link className="font-medium text-accent underline underline-offset-2" to={`/tickets/${decision.ticket_id}`}>{ticketLabel}</Link><p className="mt-0.5 text-sm text-ink-2">{decision.recommended_agent ? displayResolverName(decision.recommended_agent.display_name) : "No eligible resolver"}</p>{decision.reason ? <p className="mt-1 max-w-2xl text-xs text-muted">{decision.reason}</p> : null}{accept.error ? <div className="mt-2"><Failure error={accept.error} /></div> : null}</div>{action.canAccept ? <Button tone="accent" size="sm" disabled={accept.isPending} onClick={() => accept.mutate()}>{accept.isPending ? "Assigning…" : action.label}</Button> : <Link className="text-sm text-accent underline underline-offset-2" to={`/tickets/${decision.ticket_id}`}>{action.label}</Link>}</li>
  );
}

/** Creating a ticket that no resolver can take is a bug, not a user error.
 *
 *  This form used to offer Network, Account access, Hardware and Software, with
 *  a required skill derived from them. Not one resolver on the roster holds any
 *  of those: the skills people actually work are the incident log's own
 *  categories, which are anonymised at source. So every ticket created here was
 *  born unroutable and the queue answered "no eligible resolver" for it, for a
 *  reason nothing on screen explained.
 *
 *  The list now comes from the roster itself, so a service group can only be
 *  chosen if somebody is qualified for it, and the option says how many. The
 *  category and the required skill are one field rather than two, which also
 *  closes the free-text mismatch the interface review raised: they described
 *  the same thing and could disagree.
 */
function NewTicket({ onCreated }) {
  const triggerRef = useRef(null);
  const titleRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [created, setCreated] = useState(null);
  const [form, setForm] = useState(EMPTY_TICKET);
  const policies = useQuery({ queryKey: ["desk", "policies"], queryFn: api.listPolicies });
  const agents = useQuery({ queryKey: ["desk", "agents"], queryFn: api.listAgents });
  // With both impact and urgency the server derives priority by the ITIL
  // matrix; asking for it as well would invite a contradiction it refuses.
  const derivesPriority = Boolean(form.impact && form.urgency);

  // skill -> how many active resolvers hold it. A skill nobody holds is not an
  // option, because offering it would only produce a refusal later.
  const serviceGroups = useMemo(() => {
    const counts = new Map();
    (agents.data?.agents || []).forEach((agent) => {
      if (agent.is_active === false) return;
      (agent.skills || []).forEach((entry) => {
        const skill = entry.skill || entry;
        counts.set(skill, (counts.get(skill) || 0) + 1);
      });
    });
    return [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [agents.data]);

  useEffect(() => {
    if (!form.required_skill && serviceGroups.length) {
      setForm((current) => ({ ...current, required_skill: serviceGroups[0][0] }));
    }
  }, [serviceGroups, form.required_skill]);

  const create = useMutation({
    mutationFn: () =>
      api.createTicket({
        title: form.title.trim(),
        description: form.description.trim() || null,
        external_reference: form.external_reference.trim() || null,
        impact: form.impact ? Number(form.impact) : null,
        urgency: form.urgency ? Number(form.urgency) : null,
        priority: derivesPriority ? null : Number(form.priority),
        // One field, written to both columns: the seeded tickets do the same,
        // and two names for one fact is how they drift apart.
        category: form.required_skill || null,
        required_skill: form.required_skill || null,
      }),
    onSuccess: (data) => {
      setCreated(data.ticket);
      setForm({ ...EMPTY_TICKET, required_skill: form.required_skill });
      setOpen(false);
      onCreated();
    },
  });
  useEffect(() => { if (open) titleRef.current?.focus(); }, [open]);
  function close() { setOpen(false); requestAnimationFrame(() => triggerRef.current?.focus()); }
  const set = (field) => (event) => setForm({ ...form, [field]: event.target.value });

  return (
    <div className="w-full sm:w-auto">
      <Button ref={triggerRef} tone="accent" onClick={() => { setCreated(null); setOpen(true); }}>New ticket</Button>
      {created ? (
        <p className="mt-2 text-sm text-good" role="status">
          Created as P{created.priority}. <Link className="underline" to={`/tickets/${created.id}`}>Open it</Link>.
        </p>
      ) : null}
      {open ? (
        <section className="mt-4 border border-rule bg-surface p-4 text-left shadow-sm" aria-labelledby="new-ticket-title">
          <div className="flex items-baseline justify-between gap-3">
            <div>
              <h2 id="new-ticket-title" className="font-display text-lg text-ink">Create ticket</h2>
              <p className="mt-1 text-sm text-muted">The SLA deadline is fixed from the priority when the ticket is created.</p>
            </div>
            <Button tone="quiet" size="sm" onClick={close}>Cancel</Button>
          </div>
          <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); create.mutate(); }}>
            <div className="sm:col-span-2">
              <Field label="Title" hint="what the caller reports" htmlFor="new-title">
                <input ref={titleRef} id="new-title" className="field" required maxLength={200} value={form.title} onChange={set("title")} placeholder="Payroll portal times out for the finance team" />
              </Field>
            </div>
            <div className="sm:col-span-2">
              <Field label="Description" hint="optional" htmlFor="new-description">
                <textarea id="new-description" className="field min-h-24" maxLength={5000} value={form.description} onChange={set("description")} placeholder="What happens, since when, who is affected" />
              </Field>
            </div>
            <Field label="Impact" hint="how many are affected" htmlFor="new-impact">
              <LevelSelect id="new-impact" value={form.impact} onChange={set("impact")} />
            </Field>
            <Field label="Urgency" hint="how soon it hurts" htmlFor="new-urgency">
              <LevelSelect id="new-urgency" value={form.urgency} onChange={set("urgency")} />
            </Field>
            {derivesPriority ? (
              <p className="sm:col-span-2 border-l-2 border-accent px-3 py-2 text-sm text-ink-2">
                Priority will be derived from impact and urgency by the ITIL matrix, and the SLA target follows from it.
              </p>
            ) : (
              <>
                <Field label="Priority" hint="needed until impact and urgency are both set" htmlFor="new-priority">
                  <select id="new-priority" className="field" value={form.priority} onChange={set("priority")}>
                    {[1, 2, 3, 4].map((priority) => <option key={priority} value={priority}>P{priority}</option>)}
                  </select>
                </Field>
                <p className="self-end border-l-2 border-accent px-3 py-2 text-sm text-ink-2">{slaPreview(form.priority, policies.data?.policies)}</p>
              </>
            )}
            <Field label="Reference" hint="optional, e.g. INC0031234" htmlFor="new-reference">
              <input id="new-reference" className="field" value={form.external_reference} pattern="[A-Za-z][A-Za-z0-9-]*[0-9][A-Za-z0-9-]*" title="An uppercase code with at least one digit, such as INC0031234." onChange={(event) => setForm({ ...form, external_reference: event.target.value.toUpperCase() })} placeholder="INC0031234" />
            </Field>
            <Field label="Service group" hint="decides who can take it" htmlFor="new-skill">
              <select id="new-skill" className="field" value={form.required_skill} required onChange={set("required_skill")}>
                {serviceGroups.length === 0 ? <option value="">No resolver skills on the roster</option> : null}
                {serviceGroups.map(([skill, count]) => (<option key={skill} value={skill}>{workTypeLabel(skill)} ({count} qualified)</option>))}
              </select>
            </Field>
            {create.error ? <div className="sm:col-span-2"><Failure error={create.error} /></div> : null}
            <div className="flex gap-2 sm:col-span-2">
              <Button tone="accent" type="submit" disabled={create.isPending || !form.required_skill || !form.title.trim()}>{create.isPending ? "Creating…" : "Create ticket"}</Button>
              <Button type="button" onClick={close}>Cancel</Button>
            </div>
          </form>
        </section>
      ) : null}
    </div>
  );
}

const EMPTY_TICKET = { title: "", description: "", external_reference: "", impact: "", urgency: "", priority: "2", required_skill: "" };

function LevelSelect({ id, value, onChange }) {
  return (
    <select id={id} className="field" value={value} onChange={onChange}>
      <option value="">Not assessed</option>
      {LEVELS.map((level) => <option key={level.value} value={level.value}>{level.value} - {level.label}</option>)}
    </select>
  );
}

function Field({ label, hint, htmlFor, children }) {
  return <label className="flex flex-col gap-1 text-sm" htmlFor={htmlFor}><span className="font-medium text-ink">{label} {hint ? <span className="font-normal text-muted">({hint})</span> : null}</span>{children}</label>;
}
