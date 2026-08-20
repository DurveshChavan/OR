# Design — SLA Ticket Desk (client)

A locked design system for this app. Every page redesign reads this file before
emitting code. Do not regenerate per page — extend or amend this file when the
system needs to grow.

## Genre
modern-minimal (dev-tool / instrument-panel register — Stripe/Linear school, cool variant)

## Macrostructure family

This is a real application, not a marketing site — none of Hallmark's 21
catalog macrostructures is literally "dashboard app shell." **Workbench** is
the closest fit in spirit (content is the product, functional heading voice,
no marketing copy) and is Cobalt's own stated macrostructure affinity ("the
technical, tool-first shape"). It is applied loosely: its principle —
screenshots/panels as primary content, minimal chrome — becomes "the OR
result (table, chart, editable field) is the primary content; the page never
explains itself with marketing prose."

- App pages (all 8 routes): Workbench-derived shell — sidebar rail + a stack
  of content panels (Card). Panels vary in body: chart, table, heatmap,
  editable form, SVG diagram. No hero, no CTA-bar, no sections beyond panels.
- No marketing or content pages exist in this app.

## Theme — Cobalt

- `--color-paper`       oklch(98.5% 0.004 250)
- `--color-paper-2`     oklch(96% 0.007 250)
- `--color-surface`     oklch(99.3% 0.003 250)
- `--color-ink`         oklch(24% 0.02 258)
- `--color-ink-2`       oklch(34% 0.018 257)
- `--color-muted`       oklch(52% 0.014 256)
- `--color-rule`        oklch(89% 0.007 255)
- `--color-rule-2`      oklch(80% 0.009 255)
- `--color-accent`      oklch(52% 0.20 256)   -- electric cobalt, the one signal
- `--color-accent-ink`  oklch(99% 0.006 256)
- `--color-accent-soft` oklch(94% 0.03 256)
- `--color-focus`       oklch(52% 0.20 256)
- `--color-graphite`    oklch(22% 0.016 260)

Paper band: cool light (L 98.5%, hue ~250). Display style: grotesk-sans
(Space Grotesk). Accent hue: electric cobalt (~256°, high chroma). First
Hallmark run for this project — no prior rotation to diverge from.

**Accent tuned darker than the catalog's canonical 58%.** A ui-ux-pro-max
checklist pass measured real rendered contrast (canvas-rasterized pixel
readback, not eyeballing): accent-ink text on an accent-fill button was
4.24:1, and accent used as text on paper (card eyebrows) was 4.17:1 — both
under the 4.5:1 AA floor for normal-size text. 52% clears both with margin
(~5.3-5.8:1) at the same hue/chroma, so it's still recognizably "electric
cobalt," just one shade deeper.

### Status semantics (data colour, distinct from the brand accent)

The app reports real SLA state (breach / at-risk / safe) and cost deltas
(rise / fall). That is data semantics, not decorative accent flooding —
color.md's "one accent ≤3% of viewport" rule governs the *brand* signal
(cobalt); it does not forbid a dashboard's traffic-light vocabulary. Three
tokens, used only in status chips, table cells, bars and progress fills:

- `--color-good`          oklch(44% 0.14 152)  -- SLA safe, cost fell, resolve-in-place
- `--color-good-soft`     oklch(93% 0.045 152)
- `--color-risk`          oklch(48% 0.15 70)   -- cutting it close, escalate-L2
- `--color-risk-soft`     oklch(93% 0.055 80)
- `--color-critical`      oklch(48% 0.18 25)   -- already breaches, cost rose, escalate-vendor
- `--color-critical-soft` oklch(93% 0.05 25)
- `--color-data-neutral`  oklch(60% 0.01 256)  -- unknown / not-yet-run series

Every status is paired with a text label or icon, never colour alone (color.md
"red-green pairing as the only signal" ban).

**Also tuned darker than the first pass.** Same measured-pixel check: each
`<status>` text on its own `<status>-soft` chip background — the pairing
`StatusBadge` and the infeasible/moved-ticket callouts actually use — came
back under 4.5:1 at the original lightness (good 3.75:1, critical 4.16:1,
risk 3.06:1, worst of the three). Darkened to clear 4.5:1 with margin
(~5.4-5.8:1) at the same hue/chroma.

## Typography

- Display: Space Grotesk, weight 500/600
- Body: Inter, weight 400/500
- Mono/outlier: JetBrains Mono — status chips, table headers, sidebar
  section labels, numeric captions. Uppercase, `0.06em` tracking.
- Scale anchor: 1.25 ratio from a 16px body (`--text-*` per typography.md;
  this app never needs a hero `--text-display` — largest text on any page is
  a summary-card stat at `--text-2xl`).
- `font-variant-numeric: tabular-nums` globally — every page is dense with
  costs, minutes, percentages that must align in columns.

## Spacing

Tailwind's default spacing scale (already 4pt-based: `p-1`=4px … `p-6`=24px)
is used directly — introducing a parallel `--space-*` scale on top of an
already-systematic Tailwind scale would be duplication, not discipline.

## Motion

- Easings: `--ease-out: cubic-bezier(0.16, 1, 0.3, 1)`, applied via Tailwind's
  `ease-out` utility (redefined to this value, never the browser default).
- Reveal pattern: none. Data appears the instant it resolves — a dashboard
  that fades in its numbers reads as decorative, not calm. Motion is reserved
  for interactive-state transitions (hover, focus, active, loading spinner)
  only, motion-cut per modern-minimal genre (no framer-motion in this repo).
- Reduced-motion fallback: global `prefers-reduced-motion: reduce` collapses
  all durations to ~0 (see `index.css`).

## Microinteractions stance

- Silent success on re-solve actions (data just updates in place) — no toast.
- Buttons carry all interactive states inline (hover/focus-visible/active/
  disabled/loading via label swap).
- Focus ring: `--color-focus`, 2px, `outline-offset: 2px`, never animated in.

## CTA voice

- Primary action (Generate / Re-solve / Age / Replace): solid `--color-accent`
  fill, `--color-accent-ink` text, `--radius-control` (6px) — never a pill.
  Label is the verb + object ("Re-solve staffing"), never "Submit" / "Go".
- No secondary/outline CTA pattern needed — each panel has at most one action.

## Nav — numbered top tab strip (superseded N3 side-rail)

**Revision 2026-08-14.** The first pass used an N3-adapted left sidebar —
wordmark + boxed vertical link list. User feedback: it "still looks like a
generic admin template" regardless of the colour/type work, and they were
right — a persistent left rail of boxed nav links is *the* single most
recognisable admin-template tell there is, independent of theme. Replaced
with a full-width top bar: wordmark left, a numbered horizontal tab strip
(`01 Overview · 02 Staffing Planner · …`, underline-active not box-active,
scrolls its own row if it doesn't fit rather than wrapping or shrinking the
page) center, `⌘K` right. Collapses to a hamburger-triggered dropdown sheet
below `md`. `TopNav.jsx` (was `Sidebar.jsx`, deleted). This also frees the
240px the rail used to cost every page — content now runs full `max-w-6xl`
instead of being squeezed beside a permanent rail.

The command palette (`CommandPalette.jsx`) is unchanged and still works as a
fast secondary way to jump pages; the tab strip is now primary/always-visible
navigation, since a professor grading this in a viva needs every module one
click away, not memorised as a shortcut.

## Footer

None. This is an app shell, not a marketing page — Ft1–Ft8 are all
document-closing archetypes that don't apply to a persistent-sidebar tool.
Page-level meta (data-source provenance, e.g. "derived from real UCI-498
log vs. a documented CONFIG assumption") already lives inline in each panel's
subtitle/caption, which is where a dashboard user actually looks for it.

## Per-page allowances

- All 8 pages are app pages: enrichment forbidden — function carries the
  page (recharts bars, the heatmap, the CPM/PERT SVG, editable forms, tables).
- No stock imagery, no illustration, no hero anywhere in this app.

## What pages MUST share

- The `SLA Ticket Desk` wordmark + rail voice (Sidebar.jsx, unchanged route list).
- The accent colour and its ≤5%-of-viewport placement.
- Space Grotesk + Inter (+ JetBrains Mono for labels/status/numerics).
- The `Card` panel voice: `--radius-card` (10px), 1px `--color-rule` border,
  `--color-surface` fill, mono-uppercase eyebrow above the title when a
  panel needs one — **but not every panel is a boxed `Card`.** `Card` takes
  a `bare` prop that drops the border/surface/padding box for a hairline
  rule under the heading instead. Rule: boxed surface for interactive input
  panels and self-contained visuals (heatmaps, SVG diagrams, the game-theory
  payoff matrix); `bare` for read-only prose/result/table sections. Wall-to-
  wall boxes-in-boxes is the generic-admin-template tell this exists to kill
  — see § Nav revision above for why this mattered enough to rework mid-project.
- Read-only two-column results use `DataList` (label : value, hairline
  divider) instead of a `<table>` — a literal `<thead>/<tbody>` table reads
  as "yet another data grid" even when restyled. Multi-column read-only
  tables keep `<table>` (no simpler shape fits) but sit inside a `bare` Card
  with hairline row dividers instead of a boxed border, numeric columns
  right-aligned.
- A section's one headline number (total cost, makespan, etc.) gets real
  typographic weight — `font-display text-2xl`/`text-3xl` — instead of being
  buried in a `text-sm` sentence. Big confident numbers over small inline prose.
- The primary-button voice (§ CTA voice).
- Status semantics (§ Status semantics) — same three hues, same meaning,
  on every page that shows SLA/cost state (WorkQueue, EscalationAdvisor,
  TicketAssignment, HardwareHealth, MajorIncident).

## What pages MAY differ on

- Panel body: chart vs. table vs. heatmap vs. SVG network vs. form —
  whatever the OR technique on that page actually produces.
- Whether a panel carries an editable form (StaffingPlanner, RegionalLoad,
  MajorIncident, HardwareHealth) or is read-only (WorkQueue, EscalationAdvisor
  minus its game panel).

## Exports

### tokens.css
See `client/src/tokens.css` — the canonical, consumed file. Reproduced here
for portability:

```css
:root {
  --color-paper: oklch(98.5% 0.004 250);
  --color-paper-2: oklch(96% 0.007 250);
  --color-surface: oklch(99.3% 0.003 250);
  --color-ink: oklch(24% 0.02 258);
  --color-ink-2: oklch(34% 0.018 257);
  --color-muted: oklch(52% 0.014 256);
  --color-rule: oklch(89% 0.007 255);
  --color-rule-2: oklch(80% 0.009 255);
  --color-accent: oklch(52% 0.2 256);
  --color-accent-ink: oklch(99% 0.006 256);
  --color-accent-soft: oklch(94% 0.03 256);
  --color-focus: oklch(52% 0.2 256);
  --color-graphite: oklch(22% 0.016 260);
  --color-graphite-ink: oklch(94% 0.008 258);
  --color-good: oklch(44% 0.14 152);
  --color-good-soft: oklch(93% 0.045 152);
  --color-risk: oklch(48% 0.15 70);
  --color-risk-soft: oklch(93% 0.055 80);
  --color-critical: oklch(48% 0.18 25);
  --color-critical-soft: oklch(93% 0.05 25);
  --color-data-neutral: oklch(60% 0.01 256);

  --font-display: "Space Grotesk", ui-sans-serif, system-ui, sans-serif;
  --font-body: "Inter", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "JetBrains Mono", ui-monospace, "SFMono-Regular", monospace;

  --radius-control: 6px;
  --radius-card: 10px;
  --radius-pill: 999px;

  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --dur-fast: 140ms;
  --dur-med: 220ms;
}
```

### Tailwind v4 `@theme`
Live in `client/src/index.css` as `@theme inline { ... }`, aliasing every
token above so Tailwind generates real utilities (`bg-paper`, `text-ink-2`,
`border-rule`, `bg-accent`, `text-good`, `rounded-card`, `ease-out`, …).
No separate export needed — the app *is* the Tailwind v4 project.

DTCG `tokens.json` and shadcn/ui CSS variables are skipped: this app has no
DTCG-consuming tool and no shadcn/ui component library in its dependency
tree (`client/package.json`) — emitting either would be dead documentation,
not a usable export.
