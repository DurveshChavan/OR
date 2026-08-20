import { useState } from "react";
import Card from "../components/Card";
import EditableNumberField from "../components/EditableNumberField";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import { useIncident } from "../hooks/useIncident";

const X_SCALE = 3.2;
const COL_WIDTH = 140;
const ROW_HEIGHT = 60;

function layoutNodes(nodes) {
  // simple SVG layout: column = earliest start (rounded to a bucket so
  // near-simultaneous activities share a column), row = order within
  // that column, so parallel/merge structure is visible without a real
  // graph-layout library.
  const byEs = new Map();
  for (const n of nodes) {
    const bucket = Math.round(n.es * 10) / 10;
    if (!byEs.has(bucket)) byEs.set(bucket, []);
    byEs.get(bucket).push(n);
  }
  const buckets = [...byEs.keys()].sort((a, b) => a - b);
  const positions = {};
  buckets.forEach((bucket, colIdx) => {
    byEs.get(bucket).forEach((n, rowIdx) => {
      positions[n.activity] = { x: 60 + colIdx * COL_WIDTH, y: 40 + rowIdx * ROW_HEIGHT };
    });
  });
  return { positions, width: 60 + buckets.length * COL_WIDTH + 60, height: Math.max(...nodes.map((n) => (positions[n.activity]?.y ?? 0))) + 80 };
}

export default function MajorIncident() {
  const [deadline, setDeadline] = useState(240);
  const { data, isLoading, isError, error } = useIncident(deadline);

  if (isLoading) return <LoadingState label="Building the incident network..." />;
  if (isError) return <ErrorState error={error} />;

  const critical = new Set(data.critical_path);
  const { positions, width, height } = layoutNodes(data.nodes);
  const probabilityPct = Math.round(data.probability * 100);

  return (
    <div className="space-y-4">
      <Card
        eyebrow="Module IV · CPM/PERT"
        title="Response network"
        subtitle="Nodes positioned by earliest start (ES); critical path (zero-slack activities) in the critical colour."
      >
        <div className="overflow-x-auto">
          <svg
            width={width}
            height={height}
            className="min-w-full"
            role="img"
            aria-label={
              `Response network with ${data.nodes.length} activities. Critical path: ` +
              `${data.critical_path.join(" then ")}, total duration ${data.project_duration.toFixed(1)} hours.`
            }
          >
            {data.edges.map(([from, to]) => {
              const a = positions[from];
              const b = positions[to];
              if (!a || !b) return null;
              const onCritical = critical.has(from) && critical.has(to);
              return (
                <line
                  key={`${from}-${to}`}
                  x1={a.x + 20} y1={a.y} x2={b.x - 20} y2={b.y}
                  stroke={onCritical ? "var(--color-critical)" : "var(--color-rule-2)"}
                  strokeWidth={onCritical ? 2 : 1}
                  markerEnd="url(#arrow)"
                />
              );
            })}
            <defs>
              <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
                <path d="M0,0 L8,4 L0,8 z" fill="var(--color-data-neutral)" />
              </marker>
            </defs>
            {data.nodes.map((n) => {
              const p = positions[n.activity];
              const onCritical = critical.has(n.activity);
              return (
                <g key={n.activity} transform={`translate(${p.x},${p.y})`}>
                  <circle r={20} fill={onCritical ? "var(--color-critical-soft)" : "var(--color-paper-2)"} stroke={onCritical ? "var(--color-critical)" : "var(--color-rule-2)"} strokeWidth={2} />
                  <text textAnchor="middle" dy={-26} fontSize={11} fill="var(--color-ink-2)" fontWeight={onCritical ? 600 : 400}>
                    {n.activity}
                  </text>
                  <text textAnchor="middle" dy={4} fontSize={9} fill="var(--color-muted)">
                    {n.es.toFixed(0)}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
        <p className="mt-2 text-xs text-muted">
          Critical path: <span className="font-medium text-critical">{data.critical_path.join(" -> ")}</span>{" "}
          -- duration {data.project_duration.toFixed(1)}h
        </p>
      </Card>

      <Card title="Completion probability" subtitle="Editable deadline is a business risk-tolerance choice, not data.">
        <div className="flex items-center gap-6">
          <EditableNumberField label="Deadline (hours)" value={deadline} min={1} step={1} onChange={setDeadline} />
          <div className="flex-1">
            <div className="h-4 w-full rounded-pill bg-paper-2 overflow-hidden">
              <div
                className={`h-full transition-[width] duration-200 ease-out ${
                  probabilityPct >= 80 ? "bg-good" : probabilityPct >= 50 ? "bg-risk" : "bg-critical"
                }`}
                style={{ width: `${probabilityPct}%` }}
              />
            </div>
            <p className="mt-1 text-sm text-ink-2">
              P(finish by deadline) = <span className="font-semibold text-ink tabular-nums">{probabilityPct}%</span> (Z = {data.z.toFixed(2)})
            </p>
            {data.forces_escalation && (
              <p className="mt-1 text-xs text-risk">
                Below the risk-tolerance threshold -- this incident's tickets are forced through
                escalation regardless of their own recommendation (see Escalation Advisor).
              </p>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}
