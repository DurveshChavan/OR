// Operations — the manager's screen, and only the manager's.
//
// It used to be in a dispatcher's navigation with every control greyed out,
// which is a page that exists to tell somebody they may not use it. The route
// is now manager-only and the dispatcher is told where a rescore comes from at
// the point they need one, on the ticket.
//
// The policy table is split by what a manager is actually deciding. How long a
// priority gets, and when risk is worth a review, are policy. The four
// per-minute rates underneath are how the solver prices a choice - real inputs,
// but not the sentence "P1 gets four hours", and they sit behind a disclosure
// rather than in front of it.
//
// The one thing this screen must never imply is that editing a policy
// retroactively fixes work already decided: a stored deadline does not move,
// and a recommendation already written keeps the rates it was priced under.

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useInvalidateAll } from "../lib/session";
import { Banner, Empty, Failure, Loading } from "../components/States";
import { Section } from "../components/Bits";
import { formatMinutes } from "../lib/format";

//: What a manager decides: how long each priority gets, and how sure the model
//: has to be before a ticket is worth putting in front of somebody.
const POLICY_FIELDS = [
  ["target_minutes", "SLA target (minutes)"],
  ["escalation_threshold", "Escalation threshold (0-1)"],
];

//: How the solver prices one choice against another. Declared business inputs
//: in one currency unit per minute, none of them measured from the log - which
//: is why they are stated as weights and kept out of the policy sentence.
const COST_FIELDS = [
  ["breach_penalty_per_minute", "Past the deadline"],
  ["late_penalty_per_minute", "Late finishing"],
  ["overdue_recovery_penalty_per_minute", "Recovering an overdue ticket"],
  ["holding_cost_per_minute", "Waiting in the queue"],
];

export default function Administration() {
  return (
    <>
      <header>
        <p className="text-sm text-muted">Manager tools</p>
        <h1 className="font-display text-2xl text-ink">Operations</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Refresh risk estimates, maintain SLA policy, and keep resolver availability current.
        </p>
      </header>
      <Rescore enabled />
      <Policies enabled />
      <Agents enabled />
    </>
  );
}

function Rescore({ enabled }) {
  const invalidate = useInvalidateAll();
  const rescore = useMutation({
    mutationFn: () => api.rescore({ only_stale: false }),
    onSuccess: () => invalidate(),
  });

  return (
    <Section
      title="Manual rescore"
      note="Refreshes stored risk estimates. It assigns nobody and never moves a ticket a dispatcher already accepted."
      actions={
        <button
          type="button"
          disabled={!enabled || rescore.isPending}
          onClick={() => rescore.mutate()}
          className="rounded-[var(--radius-control)] bg-accent px-3 py-1.5 text-sm text-accent-ink disabled:opacity-50"
        >
          {rescore.isPending ? "Rescoring…" : "Rescore open tickets"}
        </button>
      }
    >
      {rescore.error ? <Failure error={rescore.error} /> : null}
      {rescore.data ? (
        <Banner title="Rescored.">
          {rescore.data.considered} considered, {rescore.data.rescored} changed,{" "}
          {rescore.data.unchanged} unchanged. An unchanged count this large is
          expected: every field the artifact reads is fixed when a ticket is
          created, so a score moves only when a ticket is edited or a different
          artifact is installed.
        </Banner>
      ) : null}
      <p className="text-xs text-muted">Refresh runs only when a manager asks for it. It does not reassign tickets.</p>
    </Section>
  );
}

function Policies({ enabled }) {
  const invalidate = useInvalidateAll();
  const policies = useQuery({ queryKey: ["desk", "policies"], queryFn: api.listPolicies });
  const [edits, setEdits] = useState({});
  const [result, setResult] = useState(null);

  const save = useMutation({
    mutationFn: ({ id, body }) => api.patchPolicy(id, body),
    onSuccess: (data) => {
      setResult(data);
      setEdits({});
      invalidate();
    },
  });

  if (policies.isLoading) return <Loading what="SLA policies" />;
  if (policies.error) {
    return <Failure error={policies.error} onRetry={() => policies.refetch()} />;
  }

  const rows = policies.data.policies;

  return (
    <Section
      title="SLA policy"
      note="How long each priority gets, and how sure the risk model has to be before a ticket is worth reviewing. Every number is a declared business input; none of it is measured from the incident log."
    >
      <Banner tone="warning" title="Edits reach future recommendations only.">
        Deadlines already stored on open tickets do not move, and a
        recommendation already written keeps the rates it was priced under. Open
        tickets of the edited priority get a reference event so the change is
        visible in their history.
      </Banner>

      {save.error ? <Failure error={save.error} /> : null}
      {result ? (
        <Banner title="Policy saved.">
          Priority {result.policy.priority} is now version {result.policy.version}
          . {result.affected_ticket_ids.length} open ticket(s) were annotated.
        </Banner>
      ) : null}

      <PolicyTable
        fields={POLICY_FIELDS}
        rows={rows}
        edits={edits}
        setEdits={setEdits}
        enabled={enabled}
        save={save}
        withSave
      />

      <details className="mt-4 border-t border-rule pt-3 text-sm">
        <summary className="cursor-pointer font-medium text-ink">
          Cost weights the solver prices with
        </summary>
        <p className="mt-2 max-w-3xl text-sm text-muted">
          One currency unit per minute each. They decide which resolver a
          recommendation prefers when two are both qualified; they do not change
          any deadline. Edit them here and save the row above.
        </p>
        <PolicyTable
          fields={COST_FIELDS}
          rows={rows}
          edits={edits}
          setEdits={setEdits}
          enabled={enabled}
        />
      </details>

      <p className="mt-2 text-xs text-muted">
        {rows[0]?.source_note}
      </p>
    </Section>
  );
}

/** One editable policy table. Two of them exist: what a manager decides, and
 *  the weights that price a choice. Both write into the same draft, so the one
 *  Save button above commits whatever was changed in either. */
function PolicyTable({ fields, rows, edits, setEdits, enabled, save, withSave }) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-rule text-left text-xs text-muted">
            <th scope="col" className="py-2 pr-3 font-medium">Priority</th>
            {fields.map(([key, label]) => (
              <th key={key} scope="col" className="py-2 pr-3 font-medium">{label}</th>
            ))}
            {withSave ? (
              <>
                <th scope="col" className="py-2 pr-3 font-medium">Version</th>
                <th scope="col" className="py-2 font-medium">
                  <span className="sr-only">Save</span>
                </th>
              </>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((policy) => {
            const draft = edits[policy.id] || {};
            return (
              <tr key={policy.id} className="border-b border-rule">
                <td className="py-2 pr-3">
                  P{policy.priority}
                  <div className="text-xs text-muted">
                    {formatMinutes(policy.target_minutes)} target
                  </div>
                </td>
                {fields.map(([key, label]) => (
                  <td key={key} className="py-2 pr-3">
                    <input
                      type="number"
                      step="any"
                      aria-label={`${label} for priority ${policy.priority}`}
                      disabled={!enabled}
                      className="w-28 rounded-[var(--radius-control)] border border-rule-2 bg-paper px-2 py-1"
                      value={draft[key] ?? policy[key]}
                      onChange={(event) =>
                        setEdits({
                          ...edits,
                          [policy.id]: { ...draft, [key]: event.target.value },
                        })
                      }
                    />
                  </td>
                ))}
                {withSave ? (
                  <>
                    <td className="py-2 pr-3">v{policy.version}</td>
                    <td className="py-2">
                      <button
                        type="button"
                        disabled={!enabled || !edits[policy.id] || save.isPending}
                        onClick={() =>
                          save.mutate({ id: policy.id, body: numeric(edits[policy.id]) })
                        }
                        className="rounded-[var(--radius-control)] border border-accent px-3 py-1 text-xs text-accent disabled:opacity-50"
                      >
                        Save
                      </button>
                    </td>
                  </>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function numeric(draft) {
  const body = {};
  Object.entries(draft || {}).forEach(([key, value]) => {
    body[key] = key === "target_minutes" ? parseInt(value, 10) : Number(value);
  });
  return body;
}

function Agents({ enabled }) {
  const invalidate = useInvalidateAll();
  const agents = useQuery({ queryKey: ["desk", "agents"], queryFn: api.listAgents });
  const [newAgent, setNewAgent] = useState({ display_name: "", wip_limit: 2, skill: "" });

  const create = useMutation({
    mutationFn: () =>
      api.createAgent({
        display_name: newAgent.display_name,
        wip_limit: Number(newAgent.wip_limit),
        skills: newAgent.skill
          ? [{ skill: newAgent.skill, efficiency_multiplier: 1.0, is_primary: true }]
          : [],
      }),
    onSuccess: () => {
      setNewAgent({ display_name: "", wip_limit: 2, skill: "" });
      invalidate();
    },
  });

  const patch = useMutation({
    mutationFn: ({ id, body }) => api.patchAgent(id, body),
    onSuccess: () => invalidate(),
  });

  if (agents.isLoading) return <Loading what="the roster" />;
  if (agents.error) {
    return <Failure error={agents.error} onRetry={() => agents.refetch()} />;
  }

  const rows = agents.data.agents;

  return (
    <Section
      title="Resolvers and skills"
      note="A resolver is eligible for a ticket only through an explicit skill record. Deactivating someone removes them from future recommendations; it does not move work they already hold."
    >
      {create.error ? <Failure error={create.error} /> : null}
      {patch.error ? <Failure error={patch.error} /> : null}

      {rows.length === 0 ? <Empty>No resolvers yet.</Empty> : null}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-rule text-left text-xs text-muted">
              <th scope="col" className="py-2 pr-2">resolver</th>
              <th scope="col" className="py-2 pr-2">skills (speed factor)</th>
              <th scope="col" className="py-2 pr-2">WIP limit</th>
              <th scope="col" className="py-2 pr-2">next free</th>
              <th scope="col" className="py-2 pr-2">active</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((agent) => (
              <tr key={agent.id} className="border-b border-rule">
                <td className="py-2 pr-2">{agent.display_name}</td>
                <td className="py-2 pr-2">
                  {agent.skills.length
                    ? agent.skills
                        .map(
                          (skill) =>
                            `${skill.skill} (${skill.efficiency_multiplier.toFixed(2)}${
                              skill.is_primary ? ", primary" : ""
                            })`
                        )
                        .join(", ")
                    : "no skills — never eligible"}
                </td>
                <td className="py-2 pr-2">
                  <input
                    type="number"
                    min="1"
                    aria-label={`WIP limit for ${agent.display_name}`}
                    disabled={!enabled}
                    className="w-20 rounded-[var(--radius-control)] border border-rule-2 bg-paper px-2 py-1"
                    defaultValue={agent.wip_limit}
                    onBlur={(event) => {
                      const wip = parseInt(event.target.value, 10);
                      if (wip && wip !== agent.wip_limit) {
                        patch.mutate({ id: agent.id, body: { wip_limit: wip } });
                      }
                    }}
                  />
                </td>
                <td className="py-2 pr-2">
                  {agent.next_available_at
                    ? new Date(agent.next_available_at).toLocaleString()
                    : "now"}
                </td>
                <td className="py-2 pr-2">
                  <button
                    type="button"
                    disabled={!enabled || patch.isPending}
                    onClick={() =>
                      patch.mutate({ id: agent.id, body: { is_active: !agent.is_active } })
                    }
                    className="rounded-[var(--radius-control)] border border-rule-2 px-2 py-1 text-xs disabled:opacity-50"
                  >
                    {agent.is_active ? "active — deactivate" : "inactive — activate"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <form
        className="mt-4 flex flex-wrap items-end gap-2 border-t border-rule pt-4"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-ink">Display name</span>
          <input
            className="rounded-[var(--radius-control)] border border-rule-2 bg-paper px-3 py-2"
            disabled={!enabled}
            value={newAgent.display_name}
            onChange={(event) =>
              setNewAgent({ ...newAgent, display_name: event.target.value })
            }
            required
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-ink">First skill</span>
          <input
            className="rounded-[var(--radius-control)] border border-rule-2 bg-paper px-3 py-2"
            disabled={!enabled}
            value={newAgent.skill}
            onChange={(event) => setNewAgent({ ...newAgent, skill: event.target.value })}
            placeholder="network"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-medium text-ink">WIP limit</span>
          <input
            type="number"
            min="1"
            className="w-24 rounded-[var(--radius-control)] border border-rule-2 bg-paper px-3 py-2"
            disabled={!enabled}
            value={newAgent.wip_limit}
            onChange={(event) =>
              setNewAgent({ ...newAgent, wip_limit: event.target.value })
            }
          />
        </label>
        <button
          type="submit"
          disabled={!enabled || create.isPending || !newAgent.display_name}
          className="rounded-[var(--radius-control)] bg-accent px-4 py-2 text-sm text-accent-ink disabled:opacity-50"
        >
          {create.isPending ? "Adding…" : "Add resolver"}
        </button>
      </form>
    </Section>
  );
}
