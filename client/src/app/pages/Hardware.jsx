// Hardware — the machine register and the replacement advice computed from it.
//
// The single most important thing this screen does is say where its numbers
// came from. They came from a person typing them in. The incident log this
// product models has no hardware telemetry and no ticket-to-asset key, so any
// screen claiming to have *detected* a failing machine would be claiming
// evidence that does not exist. What exists is an operator's asset register and
// a textbook method, and the screen shows the method's whole table so a reader
// can check the recommendation with a calculator.

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useInvalidateAll, useSession } from "../lib/session";
import { Banner, Empty, Failure, Loading } from "../components/States";
import { Section } from "../components/Bits";
import { Appear, Button } from "../components/Motion";
import { formatCost, formatMinutes } from "../lib/format";

const VERDICTS = {
  replace_now: {
    label: "Replace now",
    tone: "border-critical text-critical bg-critical-soft",
  },
  replace_soon: {
    label: "Replace soon",
    tone: "border-risk text-risk bg-risk-soft",
  },
  keep: { label: "Keep", tone: "border-good text-good bg-good-soft" },
};

export default function Hardware() {
  const { actor } = useSession();
  const isManager = actor.role === "manager";
  const [openMachine, setOpenMachine] = useState(null);

  const machines = useQuery({
    queryKey: ["desk", "machines"],
    queryFn: () => api.listMachines(),
  });
  const fleet = useQuery({
    queryKey: ["desk", "fleet-advice"],
    queryFn: () => api.fleetAdvice({ active_only: true }),
  });

  const adviceByMachine = useMemo(() => {
    const found = new Map();
    (fleet.data?.advice || []).forEach((row) => found.set(row.machine_id, row));
    return found;
  }, [fleet.data]);

  if (machines.isLoading || fleet.isLoading) return <Loading what="the machine register" />;
  if (machines.error) {
    return <Failure error={machines.error} onRetry={() => machines.refetch()} />;
  }

  const rows = machines.data.machines;
  const due = (fleet.data?.advice || []).filter(
    (row) => row.verdict === "replace_now"
  ).length;

  return (
    <div className="flex flex-col gap-4">
      <Section
        title="Machine register"
        note="Every figure here is entered by an operator from their own purchasing and maintenance records. Nothing on this screen is predicted, and nothing is derived from the incident log — it carries no hardware telemetry and no ticket-to-asset key."
      >
        <Banner tone={due ? "warning" : "neutral"} title={due ? "Attention." : "Register."}>
          {due
            ? `${due} machine(s) are past the replacement age their own cost figures imply.`
            : "No machine is past the replacement age its cost figures imply."}{" "}
          A recommendation here changes what a manager is told. It changes no
          ticket, no deadline and no assignment: dispatch never reads this
          register.
        </Banner>

        {rows.length === 0 ? (
          <Empty>
            No machines registered yet.
            {isManager ? " Add one below." : " A manager can add one."}
          </Empty>
        ) : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[820px] border-collapse text-sm">
              <caption className="sr-only">
                Registered machines with replacement advice
              </caption>
              <thead>
                <tr className="border-b border-rule text-left font-mono-label text-[10px] text-muted">
                  <th scope="col" className="py-2 pr-3">asset</th>
                  <th scope="col" className="py-2 pr-3">location</th>
                  <th scope="col" className="py-2 pr-3">type</th>
                  <th scope="col" className="py-2 pr-3">age</th>
                  <th scope="col" className="py-2 pr-3">optimal year</th>
                  <th scope="col" className="py-2 pr-3">due in</th>
                  <th scope="col" className="py-2 pr-3">linked tickets</th>
                  <th scope="col" className="py-2 pr-3">advice</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((machine) => {
                  const advice = adviceByMachine.get(machine.id);
                  const verdict = advice ? VERDICTS[advice.verdict] : null;
                  return (
                    <tr key={machine.id} className="border-b border-rule align-top">
                      <td className="py-2.5 pr-3 font-medium text-ink">
                        {machine.asset_tag}
                      </td>
                      <td className="py-2.5 pr-3">{machine.location || "—"}</td>
                      <td className="py-2.5 pr-3">{machine.machine_type}</td>
                      <td className="py-2.5 pr-3">
                        {machine.current_age_months.toFixed(0)} months
                      </td>
                      <td className="py-2.5 pr-3">
                        {advice ? `year ${advice.optimal_replacement_year}` : "—"}
                      </td>
                      <td className="py-2.5 pr-3">
                        {advice
                          ? advice.months_until_due >= 0
                            ? `${advice.months_until_due.toFixed(0)} months`
                            : `${Math.abs(advice.months_until_due).toFixed(0)} months ago`
                          : "—"}
                      </td>
                      <td className="py-2.5 pr-3">{machine.linked_tickets}</td>
                      <td className="py-2.5 pr-3">
                        {verdict ? (
                          <button
                            type="button"
                            onClick={() =>
                              setOpenMachine(
                                openMachine === machine.id ? null : machine.id
                              )
                            }
                            aria-expanded={openMachine === machine.id}
                            className={
                              "rounded-[var(--radius-pill)] border px-2.5 py-1 text-[11px] " +
                              verdict.tone
                            }
                          >
                            {verdict.label}
                          </button>
                        ) : (
                          <span className="text-muted">no cost figures</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {openMachine ? (
        <Appear>
          <MachineAdvice machineId={openMachine} onClose={() => setOpenMachine(null)} />
        </Appear>
      ) : null}

      <GroupReplacement fleetSize={rows.length} />

      {isManager ? <NewMachine /> : null}
    </div>
  );
}

function MachineAdvice({ machineId, onClose }) {
  const advice = useQuery({
    queryKey: ["desk", "machine-advice", machineId],
    queryFn: () => api.machineAdvice(machineId),
  });

  if (advice.isLoading) return <Loading what="the replacement analysis" />;
  if (advice.error) return <Failure error={advice.error} />;

  const row = advice.data.advice;
  const optimal = row.optimal_replacement_year;

  return (
    <Section
      title={`${row.asset_tag} — average annual cost`}
      note="The syllabus method: for replacement at the end of year n, total cost is purchase minus resale at n plus running cost accumulated to n, and the average is that total divided by n. The optimal year is the one where the average stops falling. A running cost that climbs year on year is what a machine getting slower and more troublesome looks like in the operator's own records — it is the reason the average turns."
      actions={
        <Button size="sm" onClick={onClose}>
          Close
        </Button>
      }
    >
      <p className="mb-3 rounded-[var(--radius-card)] border border-rule bg-paper-2 p-3 text-sm text-ink">
        {row.reason}
      </p>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-rule text-left font-mono-label text-[10px] text-muted">
              <th scope="col" className="py-2 pr-3">year</th>
              <th scope="col" className="py-2 pr-3">cumulative running cost</th>
              <th scope="col" className="py-2 pr-3">total cost</th>
              <th scope="col" className="py-2 pr-3">average annual cost</th>
            </tr>
          </thead>
          <tbody>
            {row.table.map((year) => (
              <tr
                key={year.year}
                className={
                  "border-b border-rule " +
                  (year.year === optimal ? "bg-accent-soft font-medium text-ink" : "")
                }
              >
                <td className="py-2 pr-3">{year.year}</td>
                <td className="py-2 pr-3">{formatCost(year.cumulative_running_cost)}</td>
                <td className="py-2 pr-3">{formatCost(year.total_cost)}</td>
                <td className="py-2 pr-3">
                  {formatCost(year.average_cost)}
                  {year.year === optimal ? " ← lowest" : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <dl className="mt-4 grid gap-3 sm:grid-cols-4">
        <Fact label="linked tickets">{row.evidence.linked_tickets}</Fact>
        <Fact label="still open">{row.evidence.open_linked_tickets}</Fact>
        <Fact label="hardware category">{row.evidence.hardware_category_tickets}</Fact>
        <Fact label="mean ticket risk">
          {row.evidence.mean_risk_probability === null
            ? "—"
            : `${(row.evidence.mean_risk_probability * 100).toFixed(1)}%`}
        </Fact>
      </dl>
      <p className="mt-3 text-xs text-muted">
        Linked tickets are counted, never inferred: each one was attached to this
        machine by a person, and the ticket history records who did it. The count
        is context for a manager, not an input to the replacement arithmetic —
        the verdict above comes from the cost table alone.
      </p>
      <p className="mt-1 text-xs text-muted">Figures supplied by the operator: {row.source_note}</p>
    </Section>
  );
}

function GroupReplacement({ fleetSize }) {
  const [form, setForm] = useState({
    n_items: Math.max(1, fleetSize),
    failure_prob_by_period: "0.1, 0.2, 0.3, 0.4",
    unit_replace_cost: 20,
    group_replace_cost: 5,
  });
  const run = useMutation({
    mutationFn: () =>
      api.groupAdvice({
        n_items: Number(form.n_items),
        failure_prob_by_period: form.failure_prob_by_period
          .split(",")
          .map((value) => Number(value.trim()))
          .filter((value) => !Number.isNaN(value)),
        unit_replace_cost: Number(form.unit_replace_cost),
        group_replace_cost: Number(form.group_replace_cost),
      }),
  });

  return (
    <Section
      title="Group replacement against replace-on-failure"
      note="The second replacement method, for items that fail suddenly rather than wearing out. It answers whether swapping a whole batch on a fixed interval costs less than replacing units as they fail. Every input is an operator figure describing their own fleet."
    >
      <form
        className="grid gap-3 sm:grid-cols-4"
        onSubmit={(event) => {
          event.preventDefault();
          run.mutate();
        }}
      >
        <Field label="items in the fleet">
          <input
            type="number"
            min="1"
            className="field"
            value={form.n_items}
            onChange={(event) => setForm({ ...form, n_items: event.target.value })}
          />
        </Field>
        <Field label="failure probability per period">
          <input
            className="field"
            value={form.failure_prob_by_period}
            onChange={(event) =>
              setForm({ ...form, failure_prob_by_period: event.target.value })
            }
          />
        </Field>
        <Field label="cost to replace one">
          <input
            type="number"
            step="any"
            className="field"
            value={form.unit_replace_cost}
            onChange={(event) =>
              setForm({ ...form, unit_replace_cost: event.target.value })
            }
          />
        </Field>
        <Field label="cost per unit in a group swap">
          <input
            type="number"
            step="any"
            className="field"
            value={form.group_replace_cost}
            onChange={(event) =>
              setForm({ ...form, group_replace_cost: event.target.value })
            }
          />
        </Field>
        <div className="sm:col-span-4">
          <Button tone="accent" type="submit" disabled={run.isPending}>
            {run.isPending ? "Computing…" : "Compare policies"}
          </Button>
        </div>
      </form>

      <p className="mt-2 text-xs text-muted">
        The probabilities must describe a whole life and sum to 1; a set that does
        not is refused rather than normalised silently.
      </p>

      {run.error ? (
        <div className="mt-3">
          <Failure error={run.error} />
        </div>
      ) : null}

      {run.data ? (
        <Appear className="mt-4">
          <p className="text-sm text-ink">
            Replacing on failure costs{" "}
            <strong>{formatCost(run.data.individual_average_cost)}</strong> per
            period. The cheapest group interval is{" "}
            <strong>{run.data.optimal_group_interval}</strong> period(s) at{" "}
            <strong>{formatCost(run.data.optimal_group_average_cost)}</strong>, so
            the cheaper policy is <strong>{run.data.cheaper_policy}</strong>.
          </p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[360px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-rule text-left font-mono-label text-[10px] text-muted">
                  <th scope="col" className="py-2 pr-3">group interval</th>
                  <th scope="col" className="py-2 pr-3">average cost per period</th>
                </tr>
              </thead>
              <tbody>
                {run.data.group_table.map((row) => (
                  <tr
                    key={row.interval}
                    className={
                      "border-b border-rule " +
                      (row.interval === run.data.optimal_group_interval
                        ? "bg-accent-soft font-medium text-ink"
                        : "")
                    }
                  >
                    <td className="py-2 pr-3">{row.interval}</td>
                    <td className="py-2 pr-3">{formatCost(row.average_cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Appear>
      ) : null}
    </Section>
  );
}

function NewMachine() {
  const invalidate = useInvalidateAll();
  const [form, setForm] = useState({
    asset_tag: "",
    location: "",
    machine_type: "desktop",
    age_months: 12,
    purchase_cost: 62000,
    scrap_value_by_year: "30000, 22000, 15000, 9000, 5000",
    running_cost_by_year: "4000, 7000, 12000, 20000, 32000",
    source_note: "",
  });
  const create = useMutation({
    mutationFn: () =>
      api.createMachine({
        asset_tag: form.asset_tag,
        location: form.location || null,
        machine_type: form.machine_type,
        age_months: Number(form.age_months),
        purchase_cost: Number(form.purchase_cost),
        scrap_value_by_year: numbers(form.scrap_value_by_year),
        running_cost_by_year: numbers(form.running_cost_by_year),
        source_note: form.source_note,
      }),
    onSuccess: () => {
      setForm({ ...form, asset_tag: "", location: "" });
      invalidate();
    },
  });

  return (
    <Section
      title="Register a machine"
      note="Manager only. The resale and running-cost series must describe the same years, oldest first; a single resale figure is read as constant."
    >
      <form
        className="grid gap-3 sm:grid-cols-3"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <Field label="asset tag">
          <input
            className="field"
            required
            value={form.asset_tag}
            onChange={(event) => setForm({ ...form, asset_tag: event.target.value })}
            placeholder="WS-1005"
          />
        </Field>
        <Field label="location">
          <input
            className="field"
            value={form.location}
            onChange={(event) => setForm({ ...form, location: event.target.value })}
          />
        </Field>
        <Field label="type">
          <select
            className="field"
            value={form.machine_type}
            onChange={(event) => setForm({ ...form, machine_type: event.target.value })}
          >
            {["desktop", "laptop", "server", "kiosk"].map((one) => (
              <option key={one} value={one}>
                {one}
              </option>
            ))}
          </select>
        </Field>
        <Field label="age in months">
          <input
            type="number"
            min="0"
            className="field"
            value={form.age_months}
            onChange={(event) => setForm({ ...form, age_months: event.target.value })}
          />
        </Field>
        <Field label="purchase cost">
          <input
            type="number"
            step="any"
            className="field"
            value={form.purchase_cost}
            onChange={(event) => setForm({ ...form, purchase_cost: event.target.value })}
          />
        </Field>
        <Field label="resale value by year">
          <input
            className="field"
            value={form.scrap_value_by_year}
            onChange={(event) =>
              setForm({ ...form, scrap_value_by_year: event.target.value })
            }
          />
        </Field>
        <Field label="running cost by year">
          <input
            className="field"
            value={form.running_cost_by_year}
            onChange={(event) =>
              setForm({ ...form, running_cost_by_year: event.target.value })
            }
          />
        </Field>
        <Field label="where these figures came from">
          <input
            className="field"
            required
            value={form.source_note}
            onChange={(event) => setForm({ ...form, source_note: event.target.value })}
            placeholder="asset register export, 2026-09"
          />
        </Field>
        <div className="sm:col-span-3">
          {create.error ? <Failure error={create.error} /> : null}
        </div>
        <div className="sm:col-span-3">
          <Button tone="accent" type="submit" disabled={create.isPending}>
            {create.isPending ? "Registering…" : "Register machine"}
          </Button>
        </div>
      </form>
      <p className="mt-2 text-xs text-muted">
        The source note is required for the same reason the SLA policy rows carry
        one: a screen full of costs with no stated origin is indistinguishable
        from a screen full of invented ones.
      </p>
    </Section>
  );
}

function numbers(text) {
  return text
    .split(",")
    .map((value) => Number(value.trim()))
    .filter((value) => !Number.isNaN(value));
}

function Field({ label, children }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-mono-label text-[11px] text-muted">{label}</span>
      {children}
    </label>
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
