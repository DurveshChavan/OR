// Display helpers. Nothing here decides anything; it only renders numbers the
// server already produced.
//
// Times: the API stores and returns UTC. The screens show the browser's local
// zone and name it, because a demo where two people read the same deadline
// differently is worse than one extra label.

export const DISPLAY_ZONE =
  Intl.DateTimeFormat().resolvedOptions().timeZone || "local time";

export function formatInstant(value) {
  if (!value) return "—";
  const when = new Date(value);
  if (Number.isNaN(when.getTime())) return "—";
  return when.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Minutes as a duration a person reads, e.g. "2h 05m" or "3d 4h". */
export function formatMinutes(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const total = Math.round(Math.abs(Number(value)));
  if (total < 60) return `${total}m`;
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  if (hours < 24) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
  return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

/** The SLA clock as text, because a colour alone is not an accessible state. */
export function slaClock(dueAt, now = Date.now()) {
  if (!dueAt) return { label: "no deadline", overdue: false, minutes: null };
  const minutes = (new Date(dueAt).getTime() - now) / 60000;
  if (minutes <= 0) {
    return { label: `overdue by ${formatMinutes(minutes)}`, overdue: true, minutes };
  }
  return { label: `${formatMinutes(minutes)} left`, overdue: false, minutes };
}

// These boundaries are the server's, copied from `routes/radar.py` RISK_BANDS.
// They are a display convention and not a model output, and they are written
// once here so a filter and a label cannot come to mean two different things.
export const RISK_BANDS = [
  { name: "high", low: 0.66, high: 1.01 },
  { name: "medium", low: 0.33, high: 0.66 },
  { name: "low", low: 0.0, high: 0.33 },
];

export function riskBand(probability) {
  if (probability === null || probability === undefined) return "unscored";
  const band = RISK_BANDS.find((one) => probability >= one.low && probability < one.high);
  return band ? band.name : "unscored";
}

/** The score as a band with the number beside it, never a bare percentage.
 *
 *  Phase 3 found a manually created priority-2 ticket scoring 0.999 because
 *  three fields the model was trained on do not exist in this application. A
 *  band plus the model version is an honest way to show that; a bare "99.9%"
 *  is not.
 */
export function riskLabel(probability) {
  if (probability === null || probability === undefined) return "unscored";
  return `${riskBand(probability)} · ${(probability * 100).toFixed(1)}%`;
}

export function formatCost(value) {
  if (value === null || value === undefined) return "—";
  return Number(value).toFixed(2);
}

export const PRIORITY_LABELS = { 1: "P1", 2: "P2", 3: "P3", 4: "P4" };
