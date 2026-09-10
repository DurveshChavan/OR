// Loading, empty and failure, written once so every data view has all three.
// A screen that renders nothing while a request is in flight and nothing when
// it fails looks identical to a screen with no work on it, which is the state a
// dispatcher must never mistake for calm.

export function Loading({ what = "data" }) {
  return (
    <div
      role="status"
      className="rounded-[var(--radius-card)] border border-rule bg-surface p-6 text-muted"
    >
      Loading {what}…
    </div>
  );
}

export function Empty({ children }) {
  return (
    <div className="rounded-[var(--radius-card)] border border-dashed border-rule-2 bg-paper-2 p-6 text-muted">
      {children}
    </div>
  );
}

/** A failure names its code and request id, so a screenshot is traceable. */
export function Failure({ error, onRetry }) {
  if (!error) return null;
  return (
    <div
      role="alert"
      className="rounded-[var(--radius-card)] border border-critical bg-critical-soft p-4 text-critical"
    >
      <p className="font-display text-base">{error.message}</p>
      <p className="mt-1 font-mono-label text-[11px]">
        {error.code || "REQUEST_FAILED"}
        {error.requestId ? ` · request ${error.requestId}` : ""}
      </p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 rounded-[var(--radius-control)] border border-critical px-3 py-1.5 text-sm"
        >
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function Banner({ tone = "neutral", title, children }) {
  const tones = {
    neutral: "border-rule bg-paper-2 text-ink-2",
    warning: "border-risk bg-risk-soft text-risk",
    critical: "border-critical bg-critical-soft text-critical",
  };
  return (
    <div className={`rounded-[var(--radius-card)] border p-3 text-sm ${tones[tone]}`}>
      {title ? <span className="font-display">{title} </span> : null}
      {children}
    </div>
  );
}
