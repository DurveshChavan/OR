// Small display pieces shared by the four screens.

import { riskBand, riskLabel, slaClock } from "../lib/format";

/** SLA state as text first. Colour repeats it; it never carries it alone. */
export function SlaState({ dueAt }) {
  const clock = slaClock(dueAt);
  return (
    <span
      className={
        clock.overdue
          ? "font-mono-label text-[11px] text-critical"
          : "font-mono-label text-[11px] text-ink-2"
      }
    >
      {clock.overdue ? "⚠ " : ""}
      {clock.label}
    </span>
  );
}

/** The risk score as a band and a number, with the model that produced it. */
export function RiskCell({ probability, modelVersion }) {
  const band = riskBand(probability);
  const tones = {
    high: "border-critical text-critical",
    medium: "border-risk text-risk",
    low: "border-good text-good",
    unscored: "border-rule-2 text-muted",
  };
  return (
    <span className="inline-flex flex-col gap-0.5">
      <span
        className={`inline-block w-fit rounded-[var(--radius-pill)] border px-2 py-0.5 text-[11px] ${tones[band]}`}
      >
        {riskLabel(probability)}
      </span>
      <span className="font-mono-label text-[10px] text-muted">
        {modelVersion || "no model version"}
      </span>
    </span>
  );
}

export function PriorityTag({ priority }) {
  return (
    <span className="font-mono-label text-[11px] text-ink">P{priority}</span>
  );
}

export function Section({ title, note, children, actions }) {
  return (
    <section className="rounded-[var(--radius-card)] border border-rule bg-surface p-4">
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-lg text-ink">{title}</h2>
        {actions}
      </header>
      {note ? <p className="mb-3 text-sm text-muted">{note}</p> : null}
      {children}
    </section>
  );
}
