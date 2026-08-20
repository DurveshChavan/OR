const ACT_LABEL = {
  "resolve-in-place": "Resolve",
  "escalate-L2": "Escalate L2",
  "escalate-vendor": "Vendor",
};

const ACT_STYLE = {
  "resolve-in-place": "bg-good-soft text-good",
  "escalate-L2": "bg-risk-soft text-risk",
  "escalate-vendor": "bg-critical-soft text-critical",
};

const ACT_DOT = {
  "resolve-in-place": "bg-good",
  "escalate-L2": "bg-risk",
  "escalate-vendor": "bg-critical",
};

export default function StatusBadge({ act }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-pill px-2 py-0.5 font-mono-label text-[0.6875rem] ${
        ACT_STYLE[act] || "bg-paper-2 text-muted"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${ACT_DOT[act] || "bg-data-neutral"}`} />
      {ACT_LABEL[act] || act}
    </span>
  );
}
