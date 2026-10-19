// The replacement decision, drawn.
//
// This is the part of the project that is not a service desk feature, so it is
// the part most worth showing rather than tabulating. Three views, and each one
// answers a different question a manager actually asks:
//
//   1. How much of the fleet is past its cheapest replacement year, right now?
//   2. For one machine, where does the average annual cost stop falling?
//      That turning point *is* the replacement decision, and a curve shows it
//      in a way a column of numbers does not.
//   3. Which machines are due, and in what order?
//
// Nothing here computes anything. Every number plotted is a figure the server
// returned from `/api/replacement-advice`, which got it from the same
// `api/engine/replacement.py` the oral examination checks by hand. The charts
// are a reading of that response, so a chart and the table under it cannot
// disagree.
//
// Colour never carries a verdict on its own: every series is labelled, the
// axes are named with their units, and the summary tiles repeat the verdict in
// words.

import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ReferenceDot,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const TOKEN = {
  accent: "var(--color-accent)",
  critical: "var(--color-critical)",
  risk: "var(--color-risk)",
  good: "var(--color-good)",
  rule: "var(--color-rule)",
  muted: "var(--color-muted)",
  ink: "var(--color-ink)",
  surface: "var(--color-surface)",
};

const VERDICT_COLOR = {
  replace_now: TOKEN.critical,
  replace_soon: TOKEN.risk,
  keep: TOKEN.good,
};

const VERDICT_LABEL = {
  replace_now: "Replace now",
  replace_soon: "Replace soon",
  keep: "Keep",
};

const axis = { fontSize: 11, fill: "var(--color-muted)" };

function tooltipStyle() {
  return {
    contentStyle: {
      background: TOKEN.surface,
      border: "1px solid var(--color-rule-2)",
      borderRadius: "var(--radius-control)",
      fontSize: 12,
    },
    labelStyle: { color: TOKEN.ink, fontWeight: 500 },
  };
}

/** Verdict counts, as words first and a proportion bar second. */
export function FleetVerdicts({ advice }) {
  const counts = useMemo(() => {
    const found = { replace_now: 0, replace_soon: 0, keep: 0 };
    advice.forEach((row) => {
      if (found[row.verdict] !== undefined) found[row.verdict] += 1;
    });
    return found;
  }, [advice]);
  const total = advice.length || 1;

  return (
    <div>
      <dl className="grid gap-3 sm:grid-cols-3">
        {["replace_now", "replace_soon", "keep"].map((verdict) => (
          <div
            key={verdict}
            className="rounded-[var(--radius-card)] border border-rule bg-surface px-4 py-3"
          >
            <dt className="text-sm text-muted">{VERDICT_LABEL[verdict]}</dt>
            <dd
              className="mt-1 font-display text-3xl"
              style={{ color: VERDICT_COLOR[verdict] }}
            >
              {counts[verdict]}
            </dd>
          </div>
        ))}
      </dl>
      <div
        className="mt-3 flex h-2 overflow-hidden rounded-[var(--radius-pill)] border border-rule"
        role="img"
        aria-label={`Fleet of ${advice.length}: ${counts.replace_now} replace now, ${counts.replace_soon} replace soon, ${counts.keep} keep.`}
      >
        {["replace_now", "replace_soon", "keep"].map((verdict) =>
          counts[verdict] ? (
            <span
              key={verdict}
              style={{
                width: `${(counts[verdict] / total) * 100}%`,
                background: VERDICT_COLOR[verdict],
              }}
            />
          ) : null
        )}
      </div>
    </div>
  );
}

/** The U-curve. Where it turns is the replacement year. */
export function AverageCostCurve({ advice }) {
  const data = (advice.table || []).map((row) => ({
    year: row.year,
    average: row.average_cost,
    total: row.total_cost,
  }));
  const best = data.find((row) => row.year === advice.optimal_replacement_year);

  return (
    <figure className="m-0">
      <figcaption className="text-sm text-ink-2">
        Average annual cost of keeping{" "}
        <span className="font-medium text-ink">{advice.asset_tag}</span> to the
        end of each year. It falls while the purchase price is still being spread
        over more years, then rises once the machine costs more to run than that
        saves. The lowest point is year {advice.optimal_replacement_year}.
      </figcaption>
      <div className="mt-3 h-56 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
            <CartesianGrid stroke={TOKEN.rule} vertical={false} />
            <XAxis
              dataKey="year"
              tick={axis}
              tickLine={false}
              axisLine={{ stroke: TOKEN.rule }}
              label={{ value: "year kept", position: "insideBottom", offset: -2, style: axis }}
            />
            <YAxis
              tick={axis}
              tickLine={false}
              axisLine={false}
              width={56}
              tickFormatter={(value) => Math.round(value).toLocaleString()}
            />
            <Tooltip
              {...tooltipStyle()}
              formatter={(value, name) => [
                Math.round(value).toLocaleString(),
                name === "average" ? "average annual cost" : "total cost",
              ]}
              labelFormatter={(year) => `Replaced at end of year ${year}`}
            />
            <Line
              type="monotone"
              dataKey="average"
              stroke={TOKEN.accent}
              strokeWidth={2}
              dot={{ r: 3, fill: TOKEN.accent }}
              isAnimationActive={false}
            />
            {best ? (
              <ReferenceDot
                x={best.year}
                y={best.average}
                r={6}
                fill={TOKEN.critical}
                stroke={TOKEN.surface}
                strokeWidth={2}
                isFront
                label={{
                  value: "cheapest",
                  position: "top",
                  fill: TOKEN.critical,
                  fontSize: 11,
                }}
              />
            ) : null}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

/** How far each machine is from its own cheapest year. Left of zero is late. */
export function ReplacementTimeline({ advice }) {
  const data = useMemo(
    () =>
      [...advice]
        .sort((a, b) => a.months_until_due - b.months_until_due)
        .map((row) => ({
          asset: row.asset_tag,
          months: Number(row.months_until_due.toFixed(1)),
          verdict: row.verdict,
        })),
    [advice]
  );

  return (
    <figure className="m-0">
      <figcaption className="text-sm text-ink-2">
        Months from today to each machine's cheapest replacement year. Bars to
        the left of zero are machines that passed it and have been costing more
        per year ever since.
      </figcaption>
      <div className="mt-3 w-full" style={{ height: Math.max(140, data.length * 38) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={data}
            layout="vertical"
            margin={{ top: 4, right: 16, bottom: 16, left: 4 }}
          >
            <CartesianGrid stroke={TOKEN.rule} horizontal={false} />
            <XAxis
              type="number"
              tick={axis}
              tickLine={false}
              axisLine={{ stroke: TOKEN.rule }}
              label={{ value: "months", position: "insideBottom", offset: -6, style: axis }}
            />
            <YAxis
              type="category"
              dataKey="asset"
              tick={axis}
              tickLine={false}
              axisLine={false}
              width={76}
            />
            <Tooltip
              {...tooltipStyle()}
              cursor={{ fill: "color-mix(in oklch, var(--color-paper-2) 70%, transparent)" }}
              formatter={(value) => [
                value < 0
                  ? `${Math.abs(value)} months overdue`
                  : `due in ${value} months`,
                "replacement",
              ]}
            />
            <Bar dataKey="months" radius={[0, 3, 3, 0]} isAnimationActive={false}>
              {data.map((row) => (
                <Cell key={row.asset} fill={VERDICT_COLOR[row.verdict] || TOKEN.muted} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}
