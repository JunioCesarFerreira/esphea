/** Pure builders of zigzag persistence charts. Steps: P_t at x = t, R_t at x = t - 1/2. */
import type { Data, Layout } from "plotly.js";

import type { Representative, ZigzagBars, ZigzagBatchSummary, ZigzagEvents } from "../api/types";
import { seriesColor, withAlpha, type ChartTheme } from "./chartTheme";
import { bandTraces, baseLayout } from "./plots";

export type Cause = "initial" | "variation" | "selection" | "end";

export const CAUSE_LABELS: Record<Cause, string> = {
  initial: "initial population",
  variation: "variation (offspring)",
  selection: "selection (removal)",
  end: "alive at the end",
};

export function causeColor(cause: string, theme: ChartTheme): string {
  if (cause === "variation") return seriesColor(theme, 0);
  if (cause === "selection") return seriesColor(theme, 1);
  return theme.muted;
}

export const stepX = (step: number) => step / 2;

/** Above this many bars, end markers would hide the bars themselves. */
export const MAX_BARS_WITH_MARKERS = 400;

/** ``P_t`` or ``R_t`` for a step of the zigzag. */
export function stepLabel(step: number): string {
  return step % 2 === 0 ? `P${subscript(step / 2)}` : `R${subscript((step + 1) / 2)}`;
}

function subscript(n: number): string {
  return String(n).replace(/\d/g, (d) => "₀₁₂₃₄₅₆₇₈₉"[Number(d)] ?? d);
}

interface Row {
  bar: number;
  birth: number;
  death: number;
  birthCause: string;
  deathCause: string;
}

export function barRows(bars: ZigzagBars): Row[] {
  return bars.bar
    .map((bar, i) => ({
      bar,
      birth: bars.birth[i] ?? 0,
      death: bars.death[i] ?? 0,
      birthCause: bars.birth_cause[i] ?? "initial",
      deathCause: bars.death_cause[i] ?? "end",
    }))
    .sort((a, b) => a.birth - b.birth || b.death - b.birth - (a.death - a.birth));
}

function describe(row: Row, nSteps: number): string {
  const born = `born at ${stepLabel(row.birth)} by ${CAUSE_LABELS[row.birthCause as Cause] ?? row.birthCause}`;
  const ends =
    row.death >= nSteps
      ? "alive at the end"
      : `gone at ${stepLabel(row.death)} by ${CAUSE_LABELS[row.deathCause as Cause] ?? row.deathCause}`;
  return `bar ${row.bar} · ${born}<br>${ends} · alive for ${row.death - row.birth} step(s)`;
}

/**
 * Bars over the generation axis: colour = cause of birth, end marker = cause of
 * death (circle: variation, cross: selection, arrow: alive at the end).
 */
export function zigzagBarcodeTraces(
  bars: ZigzagBars,
  theme: ChartTheme,
  selected: number | null,
): Data[] {
  const rows = barRows(bars);
  const traces: Data[] = [];
  for (const cause of ["initial", "variation", "selection"] as const) {
    const group = rows.map((row, y) => ({ row, y })).filter(({ row }) => row.birthCause === cause);
    if (group.length === 0) continue;
    traces.push({
      type: "scattergl",
      mode: "lines",
      name: `Born by ${CAUSE_LABELS[cause]}`,
      x: group.flatMap(({ row }) => [stepX(row.birth) - 0.25, stepX(row.death - 1) + 0.25, null]),
      y: group.flatMap(({ y }) => [y, y, null]),
      customdata: group.flatMap(({ row }) => [row.bar, row.bar, null]),
      text: group.flatMap(({ row }) => [
        describe(row, bars.n_steps),
        describe(row, bars.n_steps),
        "",
      ]),
      hoverinfo: "text",
      line: { color: causeColor(cause, theme), width: 2 },
    } as Data);
  }
  const symbols: Record<string, string> = {
    variation: "circle",
    selection: "x-thin",
    end: "triangle-right",
  };
  const markers = rows.length <= MAX_BARS_WITH_MARKERS ? Object.entries(symbols) : [];
  for (const [cause, symbol] of markers) {
    const group = rows.map((row, y) => ({ row, y })).filter(({ row }) => row.deathCause === cause);
    if (group.length === 0) continue;
    traces.push({
      type: "scattergl",
      mode: "markers",
      name: cause === "end" ? "Alive at the end" : `Dies by ${CAUSE_LABELS[cause as Cause]}`,
      x: group.map(({ row }) => stepX(row.death - 1) + 0.25),
      y: group.map(({ y }) => y),
      customdata: group.map(({ row }) => row.bar),
      hoverinfo: "skip",
      marker: {
        symbol,
        size: 5,
        color: theme.inkSecondary,
        line: { color: theme.inkSecondary, width: 1.5 },
      },
    } as Data);
  }
  const index = rows.findIndex((row) => row.bar === selected);
  const chosen = rows[index];
  if (chosen) {
    traces.push({
      type: "scattergl",
      mode: "lines",
      name: "Selected bar",
      x: [stepX(chosen.birth) - 0.25, stepX(chosen.death - 1) + 0.25],
      y: [index, index],
      line: { color: theme.ink, width: 5 },
      hoverinfo: "skip",
    });
  }
  return traces;
}

export function zigzagBarcodeLayout(theme: ChartTheme, nGenerations: number): Partial<Layout> {
  const layout = baseLayout(theme);
  return {
    ...layout,
    hovermode: "closest",
    xaxis: {
      ...layout.xaxis,
      title: { text: "Generation (R_t at t − ½, P_t at t)" },
      range: [-0.5, nGenerations + 0.5],
    },
    yaxis: { ...layout.yaxis, showticklabels: false, showgrid: false, title: { text: "features" } },
  };
}

/** Births (up) and deaths (down) per generation, coloured by the arrow that caused them. */
export function zigzagEventTraces(events: ZigzagEvents, theme: ChartTheme): Data[] {
  const negative = (values: number[]) => values.map((v) => -v);
  const bar = (name: string, y: number[], cause: string, births: boolean): Data => ({
    type: "bar",
    name,
    x: events.generation,
    y,
    marker: {
      color: births ? causeColor(cause, theme) : withAlpha(causeColor(cause, theme), 0.45),
    },
    hovertemplate: `${name}<br>generation %{x}<br>%{customdata}<extra></extra>`,
    customdata: y.map(Math.abs),
  });
  return [
    bar("Births · variation", events.births_variation, "variation", true),
    bar("Births · selection", events.births_selection, "selection", true),
    bar("Deaths · variation", negative(events.deaths_variation), "variation", false),
    bar("Deaths · selection", negative(events.deaths_selection), "selection", false),
  ];
}

export function zigzagBettiTraces(events: ZigzagEvents, theme: ChartTheme): Data[] {
  const color = seriesColor(theme, 0);
  return [
    {
      type: "scatter",
      mode: "lines",
      name: "after selection (Pₜ)",
      x: events.generation,
      y: events.betti_p,
      line: { color, width: 2 },
      hovertemplate: "β(P_%{x}) = %{y}<extra></extra>",
    },
    {
      type: "scatter",
      mode: "lines",
      name: "with offspring (Rₜ)",
      x: events.generation.slice(1).map((t) => t - 0.5),
      y: events.betti_r.slice(1),
      line: { color: withAlpha(color, 0.45), width: 1.5 },
      hovertemplate: "β(R) = %{y}<extra></extra>",
    },
  ];
}

/** Distribution of bar lifetimes (steps), stacked by cause of birth. */
export function lifetimeHistogramTraces(bars: ZigzagBars, theme: ChartTheme): Data[] {
  const rows = barRows(bars);
  return (["initial", "variation", "selection"] as const)
    .map((cause) => ({
      cause,
      values: rows.filter((r) => r.birthCause === cause).map((r) => r.death - r.birth),
    }))
    .filter(({ values }) => values.length > 0)
    .map(({ cause, values }) => ({
      type: "histogram",
      name: `Born by ${CAUSE_LABELS[cause]}`,
      x: values,
      marker: { color: causeColor(cause, theme) },
      xbins: { size: 1 },
    })) as Data[];
}

function coordinates(points: number[][], i: number): number[] {
  return points.map((p) => p[i] ?? Number.NaN);
}

/**
 * The population at a step (grey), the niche of an H0 representative (blue) and
 * the simplices of the representative cycle (edges in orange, vertices in ink).
 */
export function representativeTraces(view: Representative, theme: ChartTheme): Data[] {
  const nObj = view.points[0]?.length ?? 2;
  const is3d = nObj === 3;
  const position = new Map(view.members.map((id, i) => [id, view.points[i] ?? []]));
  const scatter = (points: number[][], name: string, marker: object, mode = "markers"): Data =>
    ({
      type: is3d ? "scatter3d" : "scattergl",
      mode,
      name,
      x: coordinates(points, 0),
      y: coordinates(points, 1),
      ...(is3d ? { z: coordinates(points, 2) } : {}),
      marker,
      hoverinfo: "skip",
    }) as Data;
  const traces: Data[] = [
    scatter(view.points, `Population at ${stepLabel(view.step)}`, {
      color: theme.reference,
      size: is3d ? 3 : 6,
    }),
  ];
  const component = view.component.map((id) => position.get(id) ?? []);
  if (component.length > 0) {
    traces.push(
      scatter(component, "Niche (ε-connected)", {
        color: seriesColor(theme, 0),
        size: is3d ? 4 : 8,
      }),
    );
  }
  const edges = (view.simplices ?? []).flatMap((simplex) => {
    const pairs: number[][][] = [];
    for (let a = 0; a < simplex.length; a++) {
      for (let b = a + 1; b < simplex.length; b++) {
        const p = position.get(simplex[a] ?? -1);
        const q = position.get(simplex[b] ?? -1);
        if (p && q) pairs.push([p, q]);
      }
    }
    return pairs;
  });
  if (edges.length > 0) {
    const flat = edges.flatMap(([p, q]) => [
      p ?? [],
      q ?? [],
      new Array(nObj).fill(null) as number[],
    ]);
    traces.push({
      ...scatter(flat, "Representative cycle", {}, "lines"),
      line: { color: seriesColor(theme, 1), width: is3d ? 5 : 2.5 },
    } as Data);
  }
  const vertices = [...new Set((view.simplices ?? []).flat())].map((id) => position.get(id) ?? []);
  if (vertices.length > 0) {
    traces.push(
      scatter(vertices, "Representative vertices", { color: theme.ink, size: is3d ? 4 : 7 }),
    );
  }
  return traces;
}

export type BatchView = "betti" | "births" | "deaths";

export const BATCH_VIEWS: Record<BatchView, { label: string; series: Record<string, string> }> = {
  betti: { label: "Betti number at Pₜ", series: { betti: "Betti number at Pₜ" } },
  births: {
    label: "Births",
    series: { births_variation: "Births · variation", births_selection: "Births · selection" },
  },
  deaths: {
    label: "Deaths",
    series: { deaths_variation: "Deaths · variation", deaths_selection: "Deaths · selection" },
  },
};

/** Median and interquartile band across the runs of a batch. */
export function batchTraces(
  summary: ZigzagBatchSummary,
  view: BatchView,
  theme: ChartTheme,
): Data[] {
  return Object.entries(BATCH_VIEWS[view].series).flatMap(([name, label]) => {
    const series = summary.series[name];
    if (!series) return [];
    const cause = name.endsWith("selection") ? "selection" : "variation";
    const color = name === "betti" ? seriesColor(theme, 0) : causeColor(cause, theme);
    return bandTraces(
      {
        generation: summary.generation,
        q1: series.q1,
        median: series.median,
        q3: series.q3,
        n_runs: summary.generation.map(() => summary.n_runs),
      },
      color,
      label,
    );
  });
}
