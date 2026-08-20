// `bare` drops the border/surface/padding box entirely — a hairline rule
// under the heading instead. Reserve the boxed surface for interactive
// input panels and self-contained visuals (heatmaps, SVG diagrams); read-only
// result/text sections use `bare` so the page isn't wall-to-wall boxes-in-boxes
// (the single most reliable "generic admin template" tell, independent of colour).
export default function Card({ eyebrow, title, subtitle, children, className = "", bare = false }) {
  const box = bare ? "border-b border-rule pb-1" : "rounded-card border border-rule bg-surface p-4";
  return (
    <section className={`${box} ${className}`}>
      {eyebrow && <p className="font-mono-label text-[0.6875rem] text-accent mb-1">{eyebrow}</p>}
      {title && <h2 className="font-display text-sm font-semibold text-ink">{title}</h2>}
      {subtitle && <p className="text-xs text-muted mt-0.5">{subtitle}</p>}
      <div className={title ? "mt-3" : ""}>{children}</div>
    </section>
  );
}
