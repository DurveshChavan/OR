// Screen 1 — the queue.
//
// The action is "Generate recommendations" and it is the only wording used.
// There is no "assign all" control anywhere in this file, and that is a product
// decision rather than an omission: a recommendation is not an assignment, and
// a button that turned a whole batch into assignments in one click would make
// the accept and override records meaningless.

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useInvalidateAll, useSession } from "../lib/session";
import { Banner, Empty, Failure, Loading } from "../components/States";
import { PriorityTag, RiskCell, Section, SlaState } from "../components/Bits";
import { formatInstant } from "../lib/format";

const OPEN_STATUSES = ["open", "assigned", "in_progress"];

export default function Queue() {
  const { health } = useSession();
  const invalidate = useInvalidateAll();
  const [selected, setSelected] = useState(() => new Set());
  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");

  const tickets = useQuery({
    queryKey: ["desk", "tickets", statusFilter, priorityFilter],
    queryFn: () =>
      api.listTickets({ status: statusFilter, priority: priorityFilter, limit: 200 }),
  });
  const agents = useQuery({ queryKey: ["desk", "agents"], queryFn: api.listAgents });

  const recommend = useMutation({
    mutationFn: (ticketIds) =>
      api.recommend(ticketIds, ticketIds.length > 1 ? "batch" : "single"),
    onSuccess: () => invalidate(),
  });

  const agentNames = useMemo(() => {
    const names = new Map();
    (agents.data?.agents || []).forEach((agent) =>
      names.set(agent.id, agent.display_name)
    );
    return names;
  }, [agents.data]);

  const decisionsByTicket = useMemo(() => {
    const found = new Map();
    (recommend.data?.decisions || []).forEach((decision) =>
      found.set(decision.ticket_id, decision)
    );
    return found;
  }, [recommend.data]);

  const rows = tickets.data?.tickets || [];
  const dispatchable = rows.filter((row) => OPEN_STATUSES.includes(row.status));

  function toggle(ticketId) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(ticketId)) next.delete(ticketId);
      else next.add(ticketId);
      return next;
    });
  }

  return (
    <>
      <NewTicket
        onCreated={() => {
          invalidate();
          tickets.refetch();
        }}
      />

      <Section
        title="Queue"
        note="Soonest deadline first. Selecting tickets and generating recommendations writes one immutable decision per ticket and assigns nobody."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="Filter by status"
              className="rounded-[var(--radius-control)] border border-rule-2 bg-paper px-2 py-1.5 text-sm"
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
            >
              <option value="">every status</option>
              {["open", "assigned", "in_progress", "resolved", "closed"].map((one) => (
                <option key={one} value={one}>
                  {one}
                </option>
              ))}
            </select>
            <select
              aria-label="Filter by priority"
              className="rounded-[var(--radius-control)] border border-rule-2 bg-paper px-2 py-1.5 text-sm"
              value={priorityFilter}
              onChange={(event) => setPriorityFilter(event.target.value)}
            >
              <option value="">every priority</option>
              {[1, 2, 3, 4].map((one) => (
                <option key={one} value={one}>
                  P{one}
                </option>
              ))}
            </select>
            <button
              type="button"
              disabled={
                selected.size === 0 || recommend.isPending || !health?.models_available
              }
              onClick={() => recommend.mutate([...selected])}
              className="rounded-[var(--radius-control)] bg-accent px-3 py-1.5 text-sm text-accent-ink disabled:opacity-50"
            >
              {recommend.isPending
                ? "Generating…"
                : `Generate recommendations (${selected.size})`}
            </button>
          </div>
        }
      >
        {recommend.error ? <Failure error={recommend.error} /> : null}
        {recommend.data ? (
          <Banner title="Recommendations written.">
            {recommend.data.decisions.length} immutable decision(s). Nothing is
            assigned until someone accepts or overrides one on its ticket page.
          </Banner>
        ) : null}

        {tickets.isLoading ? <Loading what="the queue" /> : null}
        {tickets.error ? (
          <Failure error={tickets.error} onRetry={() => tickets.refetch()} />
        ) : null}
        {tickets.data && rows.length === 0 ? (
          <Empty>No tickets match this filter.</Empty>
        ) : null}

        {rows.length ? (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[860px] border-collapse text-sm">
              <caption className="sr-only">
                Open tickets with SLA state and risk
              </caption>
              <thead>
                <tr className="border-b border-rule text-left font-mono-label text-[10px] text-muted">
                  <th scope="col" className="py-2 pr-2">pick</th>
                  <th scope="col" className="py-2 pr-2">reference</th>
                  <th scope="col" className="py-2 pr-2">priority</th>
                  <th scope="col" className="py-2 pr-2">skill</th>
                  <th scope="col" className="py-2 pr-2">opened</th>
                  <th scope="col" className="py-2 pr-2">SLA</th>
                  <th scope="col" className="py-2 pr-2">risk</th>
                  <th scope="col" className="py-2 pr-2">assignee</th>
                  <th scope="col" className="py-2 pr-2">recommendation</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((ticket) => {
                  const decision = decisionsByTicket.get(ticket.id);
                  const canDispatch = OPEN_STATUSES.includes(ticket.status);
                  return (
                    <tr key={ticket.id} className="border-b border-rule align-top">
                      <td className="py-2 pr-2">
                        <input
                          type="checkbox"
                          aria-label={`Select ${ticket.external_reference || ticket.id}`}
                          disabled={!canDispatch}
                          checked={selected.has(ticket.id)}
                          onChange={() => toggle(ticket.id)}
                        />
                      </td>
                      <td className="py-2 pr-2">
                        <Link
                          className="text-accent underline"
                          to={`/tickets/${ticket.id}`}
                        >
                          {ticket.external_reference || ticket.id.slice(0, 8)}
                        </Link>
                        <div className="text-[11px] text-muted">{ticket.status}</div>
                      </td>
                      <td className="py-2 pr-2">
                        <PriorityTag priority={ticket.priority} />
                      </td>
                      <td className="py-2 pr-2">{ticket.required_skill || "—"}</td>
                      <td className="py-2 pr-2">{formatInstant(ticket.opened_at)}</td>
                      <td className="py-2 pr-2">
                        <SlaState dueAt={ticket.sla_due_at} />
                      </td>
                      <td className="py-2 pr-2">
                        <RiskCell
                          probability={ticket.risk_probability}
                          modelVersion={ticket.risk_model_version}
                        />
                      </td>
                      <td className="py-2 pr-2">
                        {ticket.current_assignee_id
                          ? agentNames.get(ticket.current_assignee_id) ||
                            "unknown resolver"
                          : "unassigned"}
                      </td>
                      <td className="py-2 pr-2">
                        {decision ? (
                          <span>
                            {decision.state}
                            {decision.recommended_agent
                              ? ` · ${decision.recommended_agent.display_name}`
                              : ""}
                          </span>
                        ) : (
                          <span className="text-muted">open the ticket</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}

        <p className="mt-3 text-xs text-muted">
          {dispatchable.length} of {tickets.data?.total ?? 0} ticket(s) can be
          dispatched. A closed ticket cannot be selected.
        </p>
      </Section>
    </>
  );
}

function NewTicket({ onCreated }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    external_reference: "",
    priority: 2,
    category: "Network",
    required_skill: "network",
  });
  const create = useMutation({
    mutationFn: () =>
      api.createTicket({
        external_reference: form.external_reference || null,
        priority: Number(form.priority),
        category: form.category || null,
        required_skill: form.required_skill || null,
      }),
    onSuccess: () => {
      setOpen(false);
      onCreated();
    },
  });

  if (!open) {
    return (
      <div>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="rounded-[var(--radius-control)] border border-rule-2 bg-surface px-3 py-1.5 text-sm"
        >
          New ticket
        </button>
      </div>
    );
  }

  return (
    <Section
      title="New ticket"
      note="The deadline comes from the SLA policy for the chosen priority; it is not typed in."
    >
      <form
        className="grid gap-3 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <Field label="Reference">
          <input
            className="w-full rounded-[var(--radius-control)] border border-rule-2 bg-paper px-3 py-2"
            value={form.external_reference}
            onChange={(event) =>
              setForm({ ...form, external_reference: event.target.value })
            }
            placeholder="INC-DEMO-0100"
          />
        </Field>
        <Field label="Priority">
          <select
            className="w-full rounded-[var(--radius-control)] border border-rule-2 bg-paper px-3 py-2"
            value={form.priority}
            onChange={(event) => setForm({ ...form, priority: event.target.value })}
          >
            {[1, 2, 3, 4].map((one) => (
              <option key={one} value={one}>
                P{one}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Category">
          <input
            className="w-full rounded-[var(--radius-control)] border border-rule-2 bg-paper px-3 py-2"
            value={form.category}
            onChange={(event) => setForm({ ...form, category: event.target.value })}
          />
        </Field>
        <Field label="Required skill">
          <input
            className="w-full rounded-[var(--radius-control)] border border-rule-2 bg-paper px-3 py-2"
            value={form.required_skill}
            onChange={(event) =>
              setForm({ ...form, required_skill: event.target.value })
            }
          />
        </Field>
        <div className="sm:col-span-2">
          {create.error ? <Failure error={create.error} /> : null}
        </div>
        <div className="flex gap-2 sm:col-span-2">
          <button
            type="submit"
            disabled={create.isPending}
            className="rounded-[var(--radius-control)] bg-accent px-4 py-2 text-sm text-accent-ink disabled:opacity-60"
          >
            {create.isPending ? "Creating…" : "Create ticket"}
          </button>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="rounded-[var(--radius-control)] border border-rule-2 px-4 py-2 text-sm"
          >
            Cancel
          </button>
        </div>
      </form>
    </Section>
  );
}

function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-mono-label text-[11px] text-muted">{label}</span>
      {children}
    </label>
  );
}
