import { useEffect, useState } from "react";
import Card from "../components/Card";
import StatTile from "../components/StatTile";
import EditableNumberField from "../components/EditableNumberField";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import { useGenerateScenario } from "../hooks/useScenario";

const DEFAULTS = { n_tickets: 50, n_agents: 150, n_workstations: 20, seed: 42 };

export default function Overview() {
  const [form, setForm] = useState(DEFAULTS);
  const generate = useGenerateScenario();

  // load a default scenario once on first visit so the app isn't empty
  useEffect(() => {
    generate.mutate(DEFAULTS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const scenario = generate.data;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-4 items-start">
      <div className="space-y-4">
        <Card eyebrow="Scenario" title="Scenario controls" subtitle="Generates a fresh synthetic ticket/agent/workstation universe, fitted to the real incident log when it's cached.">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <EditableNumberField label="Tickets" value={form.n_tickets} min={1} onChange={(v) => setForm((f) => ({ ...f, n_tickets: v }))} />
            <EditableNumberField label="Agents" value={form.n_agents} min={1} onChange={(v) => setForm((f) => ({ ...f, n_agents: v }))} />
            <EditableNumberField label="Workstations" value={form.n_workstations} min={1} onChange={(v) => setForm((f) => ({ ...f, n_workstations: v }))} />
            <EditableNumberField label="Seed" value={form.seed} min={0} onChange={(v) => setForm((f) => ({ ...f, seed: v }))} />
          </div>
          <button
            className="mt-4 rounded-control bg-accent text-accent-ink text-sm font-medium px-4 py-2 hover:brightness-110 transition-[filter] duration-150 ease-out disabled:opacity-50"
            onClick={() => generate.mutate(form)}
            disabled={generate.isPending}
          >
            {generate.isPending ? "Generating..." : "Generate"}
          </button>
        </Card>

        {generate.isPending && <LoadingState label="Generating scenario..." />}
        {generate.isError && <ErrorState error={generate.error} />}

        {scenario && (
          <Card bare eyebrow="Provenance" title="Data source" subtitle="Where every derived number on the other pages actually comes from.">
            <p className="text-sm text-ink-2">{scenario.data_source}</p>
            <ul className="mt-3 space-y-2">
              {Object.entries(scenario.derived_sources).map(([name, source]) => (
                <li key={name} className="text-xs text-muted">
                  <span className="font-medium text-ink-2">{name}: </span>
                  {source}
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>

      {scenario && (
        <aside className="rounded-card border border-rule bg-paper-2 p-4 lg:sticky lg:top-6">
          <p className="font-mono-label text-[0.6875rem] text-accent mb-3">This universe</p>
          <div className="grid grid-cols-2 gap-4">
            <StatTile label="Tickets" value={scenario.n_tickets} accent />
            <StatTile label="Agents" value={scenario.n_agents} />
            <StatTile label="Workstations" value={scenario.n_workstations} />
            <StatTile label="Seed" value={scenario.seed} />
          </div>
        </aside>
      )}
    </div>
  );
}
