export default function LoadingState({ label = "Loading..." }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 text-muted text-sm py-6">
      <span aria-hidden="true" className="inline-block h-3 w-3 rounded-full border-2 border-rule-2 border-t-accent animate-spin" />
      {label}
    </div>
  );
}
