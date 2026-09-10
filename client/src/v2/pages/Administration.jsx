// Screen 4 — administration. Manager-only for every write.
//
// A dispatcher can read this screen, because knowing the WIP limits and the
// policy rates is part of reading a recommendation, but every control is
// disabled for them and the server refuses the call regardless. The one thing
// this screen must never imply is that editing a policy retroactively fixes
// work already decided: a stored deadline does not move, and a recommendation
// already written keeps the rates it was priced under.

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { v2 } from "../lib/api";
import { useInvalidateV2, useSession } from "../lib/session";
import { Banner, Empty, Failure, Loading } from "../components/States";
import { Section } from "../components/Bits";
import { formatMinutes } from "../lib/format";

const POLICY_FIELDS = [
  ["target_minutes", "target minutes"],
  ["breach_penalty_per_minute", "breach / min"],
  ["late_penalty_per_minute", "late / min"],
  ["overdue_recovery_penalty_per_minute", "overdue recovery / min"],
  ["holding_cost_per_minute", "holding / min"],
  ["escalation_threshold", "escalation threshold"],
];

export default function Administration() {
  const { actor } = useSession();
  const isManager = actor.role === "manager";

  return (
    <>
      {isManager ? null : (
        <Banner title="Read-only.">
          Administration writes are manager actions. You are signed in as a{" "}
          {actor.role}, so the controls below are disabled and the API would
          refuse them anyway.
        </Banner>
      )}
      <Rescore enabled={isManager} />
      <Policies enabled={isManager} />
      <Agents enabled={isManager} />
    </>
  );
}

function Rescore({ enabled }) {
  const invalidate = useInvalidateV2();
  const rescore = useMutation({
    mutationFn: () => v2.rescore({ only_stale: false }),
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
      <p className="text-xs text-muted">
        The same operation runs from the command line as{" "}
        <code>python -m api.app_v2.cli.rescore_open_tickets</code>. There is no
        background worker in this build, so nothing rescores on a timer.
      </p>
    </Section>
  );
}

function Policies({ enabled }) {
  const invalidate = useInvalidateV2();
  const policies = useQuery({ queryKey: ["v2", "policies"], queryFn: v2.listPolicies });
  const [edits, setEdits] = useState({});
  const [result, setResult] = useState(null);

  const save = useMutation({
    mutationFn: ({ id, body }) => v2.patchPolicy(id, body),
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
      note="Every number here is a declared business input in one currency unit per minute. None of it is measured from the log."
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

      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[860px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-rule text-left font-mono-label text-[10px] text-muted">
              <th scope="col" className="py-2 pr-2">priority</th>
              {POLICY_FIELDS.map(([key, label]) => (
                <th key={key} scope="col" className="py-2 pr-2">{label}</th>
              ))}
              <th scope="col" className="py-2 pr-2">version</th>
              <th scope="col" className="py-2 pr-2">save</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((policy) => {
              const draft = edits[policy.id] || {};
              return (
                <tr key={policy.id} className="border-b border-rule">
                  <td className="py-2 pr-2">
                    P{policy.priority}
                    <div className="text-[11px] text-muted">
                      {formatMinutes(policy.target_minutes)} target
                    </div>
                  </td>
                  {POLICY_FIELDS.map(([key]) => (
                    <td key={key} className="py-2 pr-2">
                      <input
                        type="number"
                        step="any"
                        aria-label={`${key} for priority ${policy.priority}`}
                        disabled={!enabled}
                        className="w-24 rounded-[var(--radius-control)] border border-rule-2 bg-paper px-2 py-1"
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
                  <td className="py-2 pr-2">v{policy.version}</td>
                  <td className="py-2 pr-2">
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
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-2 text-xs text-muted">
        {rows[0]?.source_note}
      </p>
    </Section>
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
  const invalidate = useInvalidateV2();
  const agents = useQuery({ queryKey: ["v2", "agents"], queryFn: v2.listAgents });
  const [newAgent, setNewAgent] = useState({ display_name: "", wip_limit: 2, skill: "" });

  const create = useMutation({
    mutationFn: () =>
      v2.createAgent({
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
    mutationFn: ({ id, body }) => v2.patchAgent(id, body),
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
            <tr className="border-b border-rule text-left font-mono-label text-[10px] text-muted">
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
          <span className="font-mono-label text-[11px] text-muted">display name</span>
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
          <span className="font-mono-label text-[11px] text-muted">first skill</span>
          <input
            className="rounded-[var(--radius-control)] border border-rule-2 bg-paper px-3 py-2"
            disabled={!enabled}
            value={newAgent.skill}
            onChange={(event) => setNewAgent({ ...newAgent, skill: event.target.value })}
            placeholder="network"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-mono-label text-[11px] text-muted">WIP limit</span>
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
