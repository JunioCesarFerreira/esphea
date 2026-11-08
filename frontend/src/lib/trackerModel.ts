/**
 * Heuristic niche trackers beside the zigzag H₀ barcode: labels, colours,
 * across-run statistics and chart builders (pure, unit tested).
 */
import type { Data, Layout } from "plotly.js";

import type { MethodRuns, MethodSummary, TrackerBars, TrackerRuns } from "../api/types";
import { seriesColor, withAlpha, type ChartTheme } from "./chartTheme";
import { baseLayout } from "./plots";
import { stepLabel, stepX } from "./zigzagPlots";

export const METHODS = ["zigzag", "t1", "t1o", "t2"] as const;
export type Method = (typeof METHODS)[number];
export type Tracker = Exclude<Method, "zigzag">;
export const TRACKERS: readonly Tracker[] = ["t1", "t1o", "t2"];

/** A bar is long when it lives at least this many steps (25 generations). */
export const DEFAULT_LONG_LIFETIME = 50;

export const METHOD_LABELS: Record<Method, string> = {
  zigzag: "Zigzag",
  t1: "T1",
  t1o: "T1o",
  t2: "T2",
};

export const METHOD_DESCRIPTIONS: Record<Method, string> = {
  zigzag: "Zigzag persistence: births and deaths paired globally over the whole run.",
  t1: "T1 sees every Pₜ and Rₜ. At a merge the oldest bar continues (the elder rule of persistence); at a split the largest fragment keeps the bar, as in the tracking graphs of scientific visualisation.",
  t1o: "T1o is T1 except at a split, where the fragment holding the oldest individual keeps the bar.",
  t2: "T2 sees only the populations Pₜ and links niches through shared survivors, as cluster and community trackers do (MONIC, Greene et al.). It never sees Rₜ: births by offspring and merges through offspring are dated at Pₜ, one step after the zigzag, so compare it by generation.",
};

/** Palette slots of the trackers (the zigzag, the reference, is drawn in ink). Checked
 * together for colour-vision deficiency; the charts add dashes and labels as well. */
const TRACKER_SLOTS: Record<Tracker, number> = { t1: 2, t1o: 3, t2: 6 };
const DASHES: Record<Method, string> = { zigzag: "solid", t1: "dash", t1o: "dot", t2: "dashdot" };

export function methodColor(theme: ChartTheme, method: Method): string {
  return method === "zigzag" ? theme.ink : seriesColor(theme, TRACKER_SLOTS[method]);
}

export type Resolution = "step" | "generation";

export const RESOLUTION_LABELS: Record<Resolution, string> = {
  step: "Same steps",
  generation: "Same generations",
};

// --- one run ------------------------------------------------------------------------

interface TrackerRow {
  birth: number;
  death: number;
  matched: boolean;
}

export function trackerRows(bars: TrackerBars, resolution: Resolution): TrackerRow[] {
  const flags = resolution === "step" ? bars.matched_step : bars.matched_generation;
  return bars.birth
    .map((birth, i) => ({ birth, death: bars.death[i] ?? birth, matched: flags[i] ?? false }))
    .sort((a, b) => a.birth - b.birth || b.death - b.birth - (a.death - a.birth));
}

function describeRow(row: TrackerRow, bars: TrackerBars): string {
  const ends = row.death >= bars.n_steps ? "alive at the end" : `gone at ${stepLabel(row.death)}`;
  const zigzag = row.matched ? "the zigzag has this bar" : "no such bar in the zigzag";
  return `${METHOD_LABELS[bars.method]} · born at ${stepLabel(row.birth)} · ${ends}<br>alive for ${row.death - row.birth} step(s) · ${zigzag}`;
}

/** The tracker's bars: grey where the zigzag has the same bar, in colour where it has not. */
export function trackerBarcodeTraces(
  bars: TrackerBars,
  resolution: Resolution,
  theme: ChartTheme,
): Data[] {
  const rows = trackerRows(bars, resolution).map((row, y) => ({ row, y }));
  return [true, false].flatMap((matched) => {
    const group = rows.filter(({ row }) => row.matched === matched);
    if (group.length === 0) return [];
    const text = group.flatMap(({ row }) => {
      const label = describeRow(row, bars);
      return [label, label, ""];
    });
    return [
      {
        type: "scattergl",
        mode: "lines",
        name: matched ? "Same bar in the zigzag" : "Not in the zigzag",
        x: group.flatMap(({ row }) => [stepX(row.birth) - 0.25, stepX(row.death - 1) + 0.25, null]),
        y: group.flatMap(({ y }) => [y, y, null]),
        text,
        hoverinfo: "text",
        line: { color: matched ? theme.reference : methodColor(theme, bars.method), width: 2 },
      } as Data,
    ];
  });
}

/** Number of bars alive at least L steps, per method (log scale: zero counts are left out). */
export function atLeastTraces(methods: MethodSummary[], theme: ChartTheme): Data[] {
  return methods.map((summary) => {
    const method = summary.method as Method;
    const x: number[] = [];
    const y: number[] = [];
    summary.at_least.forEach((count, i) => {
      if (count > 0) {
        x.push(i + 1);
        y.push(count);
      }
    });
    return {
      type: "scatter",
      mode: "lines",
      name: METHOD_LABELS[method] ?? summary.method,
      x,
      y,
      line: {
        color: methodColor(theme, method),
        width: 2,
        dash: DASHES[method] ?? "solid",
        shape: "hv",
      },
      hovertemplate: `${METHOD_LABELS[method] ?? summary.method}: %{y} bars<extra></extra>`,
    } as Data;
  });
}

export function atLeastLayout(theme: ChartTheme): Partial<Layout> {
  const layout = baseLayout(theme);
  return baseLayout(theme, {
    hovermode: "x unified",
    xaxis: { ...layout.xaxis, title: { text: "lifetime of at least L steps" } },
    yaxis: { ...layout.yaxis, title: { text: "bars" }, type: "log", dtick: 1 },
  });
}

// --- across runs ----------------------------------------------------------------------

export type RunField = keyof MethodRuns;

export const RUN_FIELDS: Record<RunField, { label: string; share: boolean }> = {
  n_long: { label: "Long bars", share: false },
  n_bars: { label: "Bars", share: false },
  median_lifetime: { label: "Median lifetime (steps)", share: false },
  p90_lifetime: { label: "90th percentile of lifetime (steps)", share: false },
  agreement_step: { label: "Zigzag bars reproduced · same steps", share: true },
  agreement_generation: { label: "Zigzag bars reproduced · same generations", share: true },
  long_agreement_step: { label: "Long zigzag bars reproduced · same steps", share: true },
  long_agreement_generation: {
    label: "Long zigzag bars reproduced · same generations",
    share: true,
  },
};

/** Quantities that describe a barcode by itself, so experiments can be ranked by them. */
export const DESCRIPTIVE_FIELDS: readonly RunField[] = [
  "n_long",
  "n_bars",
  "median_lifetime",
  "p90_lifetime",
];

export function formatShare(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(100 * value).toFixed(1)}%`;
}

const present = (values: readonly (number | null)[]): number[] =>
  values.filter((v): v is number => v !== null && !Number.isNaN(v));

export interface Spread {
  q1: number;
  median: number;
  q3: number;
  n: number;
}

/** Quartiles with linear interpolation (as numpy's default), ignoring missing values. */
export function quartiles(values: readonly (number | null)[]): Spread | null {
  const sorted = present(values).sort((a, b) => a - b);
  if (sorted.length === 0) return null;
  const at = (p: number) => {
    const position = (sorted.length - 1) * p;
    const low = Math.floor(position);
    const high = Math.ceil(position);
    const a = sorted[low] ?? 0;
    const b = sorted[high] ?? a;
    return a + (b - a) * (position - low);
  };
  return { q1: at(0.25), median: at(0.5), q3: at(0.75), n: sorted.length };
}

/** Vargha–Delaney A₁₂: probability that a value of ``x`` exceeds one of ``y`` (ties count half). */
export function a12(x: readonly (number | null)[], y: readonly (number | null)[]): number | null {
  const a = present(x);
  const b = present(y);
  if (a.length === 0 || b.length === 0) return null;
  let wins = 0;
  for (const u of a) {
    for (const v of b) wins += u > v ? 1 : u === v ? 0.5 : 0;
  }
  return wins / (a.length * b.length);
}

export type Direction = "higher" | "lower" | "similar";

/** Direction of an A₁₂, with Vargha and Delaney's threshold of a small effect. */
export function direction(value: number | null): Direction | null {
  if (value === null) return null;
  if (value >= 0.56) return "higher";
  if (value <= 0.44) return "lower";
  return "similar";
}

/** Box per method of one set of runs, coloured by method. */
export function methodBoxTraces(runs: TrackerRuns, field: RunField, theme: ChartTheme): Data[] {
  return METHODS.flatMap((method) => {
    const values = present(runs.methods[method]?.[field] ?? []);
    if (values.length === 0) return [];
    const color = methodColor(theme, method);
    return [
      {
        type: "box",
        name: METHOD_LABELS[method],
        x: values.map(() => METHOD_LABELS[method]),
        y: values,
        boxpoints: "all",
        jitter: 0.4,
        pointpos: 0,
        marker: { color, size: 5 },
        line: { color, width: 1.5 },
        fillcolor: withAlpha(color, 0.12),
        hoverinfo: "y",
      } as Data,
    ];
  });
}

/** Boxes grouped by method, one colour per experiment. */
export function experimentBoxTraces(
  series: { name: string; color: string; runs: TrackerRuns }[],
  field: RunField,
): Data[] {
  return series.map(({ name, color, runs }) => {
    const x: string[] = [];
    const y: number[] = [];
    for (const method of METHODS) {
      for (const value of present(runs.methods[method]?.[field] ?? [])) {
        x.push(METHOD_LABELS[method]);
        y.push(value);
      }
    }
    return {
      type: "box",
      name,
      x,
      y,
      boxpoints: "all",
      jitter: 0.4,
      pointpos: 0,
      marker: { color, size: 4 },
      line: { color, width: 1.5 },
      fillcolor: withAlpha(color, 0.12),
      hoverinfo: "y",
    } as Data;
  });
}

/** ``grouped``: several boxes (experiments) per method; otherwise one box per method. */
export function boxLayout(theme: ChartTheme, field: RunField, grouped: boolean): Partial<Layout> {
  const layout = baseLayout(theme);
  const share = RUN_FIELDS[field].share;
  return baseLayout(theme, {
    boxmode: grouped ? "group" : "overlay",
    xaxis: { ...layout.xaxis, title: { text: "method" } },
    yaxis: {
      ...layout.yaxis,
      title: { text: RUN_FIELDS[field].label },
      ...(share ? { tickformat: ".0%", range: [0, 1.02] } : {}),
    },
  });
}
