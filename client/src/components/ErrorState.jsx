export default function ErrorState({ error }) {
  return (
    <div role="alert" className="rounded-control border border-critical/30 bg-critical-soft text-critical text-sm p-4">
      <p className="font-medium">Something went wrong.</p>
      <p className="mt-1">{error?.message || String(error)}</p>
    </div>
  );
}
