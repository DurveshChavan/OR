// Small display pieces shared by the four screens.

import { riskBand, riskLabel, slaClock } from "../lib/format";

/** SLA state as text first. Colour repeats it; it never carries it alone. */
export function SlaState({ dueAt }) {
  const clock = slaClock(dueAt);
  return (
    <span
      className={
        clock.overdue
          ? "text-sm font-medium text-critical"
          : "text-sm text-ink-2"
      }
    >
      {clock.label}
    </span>
  );
}

/** The risk score is operational language first; provenance stays on details. */
export function RiskCell({ probability }) {
  const band = riskBand(probability);
  const tones = {
    high: "border-critical text-critical",
    medium: "border-risk text-risk",
    low: "border-good text-good",
    unscored: "border-rule-2 text-muted",
  };
  return (
    <span
      className={`inline-block w-fit rounded-[var(--radius-pill)] border px-2 py-0.5 text-[11px] ${tones[band]}`}
    >
      {riskLabel(probability)}
    </span>
  );
}

export function PriorityTag({ priority }) {
  return <span className="font-medium text-ink">P{priority}</span>;
}

export function Section({ title, note, children, actions, className = "" }) {
  return (
    <section className={`border-t border-rule pt-4 ${className}`}>
      <header className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-lg text-ink">{title}</h2>
        {actions}
      </header>
      {note ? <p className="mb-3 max-w-3xl text-sm text-muted">{note}</p> : null}
      {children}
    </section>
  );
}
