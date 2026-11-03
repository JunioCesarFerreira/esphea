/** Pure builders of Plotly traces and layouts (no React, unit tested). */
import type { Data, Layout } from "plotly.js";

import type {
  GenerationSnapshot,
  IndicatorSummary,
  MetricSeries,
  SnapshotGroup,
} from "../api/types";
import { seriesColor, withAlpha, type ChartTheme } from "./chartTheme";

const MARKER_SIZE = { 2: 8, 3: 4 } as const;

export type Layer = "population" | "offspring" | "discarded" | "front";

export const LAYER_LABELS: Record<Layer, string> = {
  population: "Parents Pₜ",
  offspring: "Offspring Qₜ",
  discarded: "Discarded",
  front: "True front",
};

const objectiveLabel = (i: number) => `f${i + 1}`;

function column(points: number[][], i: number): number[] {
  return points.map((point) => point[i] ?? Number.NaN);
}

function pointsTrace(
  points: number[][],
  nObj: number,
  options: {
    name: string;
    color: string;
    open?: boolean;
    size?: number;
    text?: string[];
    legendgroup?: string;
  },
): Data {
  const size = options.size ?? (nObj === 2 ? MARKER_SIZE[2] : MARKER_SIZE[3]);
  const marker = {
    color: options.open ? "rgba(0,0,0,0)" : options.color,
    size,
    line: { color: options.color, width: options.open ? 1.5 : 0 },
  };
  const common = {
    name: options.name,
    legendgroup: options.legendgroup ?? options.name,
    mode: "markers" as const,
    text: options.text,
    hovertemplate: options.text
      ? "%{text}<br>" +
        Array.from(
          { length: nObj },
          (_, i) => `${objectiveLabel(i)}=%{${["x", "y", "z"][i]}:.4f}`,
        ).join("<br>") +
        "<extra></extra>"
      : undefined,
  };
  if (nObj === 2) {
    return { ...common, type: "scattergl", x: column(points, 0), y: column(points, 1), marker };
  }
  return {
    ...common,
    type: "scatter3d",
    x: column(points, 0),
    y: column(points, 1),
    z: column(points, 2),
    marker: { ...marker, line: { ...marker.line, width: options.open ? 1 : 0 } },
  };
}

function describe(group: SnapshotGroup, role: "P" | "Q", index: number): string {
  const rank = group.rank[index] ?? -1;
  const parents = group.parents[index] ?? [-1, -1];
  const lines = [
    `${role}[${index}] · ${group.survived[index] ? `survived (rank ${rank})` : "discarded"}`,
  ];
  if (role === "Q") {
    lines.push(
      `parents P[${parents[0]}], P[${parents[1]}]${group.mutated[index] ? " · mutated" : ""}`,
    );
  } else {
    lines.push(`selected for ${group.times_selected[index] ?? 0} mating(s)`);
  }
  return lines.join("<br>");
}

function split(group: SnapshotGroup, role: "P" | "Q") {
  const kept: number[][] = [];
  const keptText: string[] = [];
  const lost: number[][] = [];
  const lostText: string[] = [];
  group.F.forEach((point, i) => {
    const target = group.survived[i] ? kept : lost;
    (group.survived[i] ? keptText : lostText).push(describe(group, role, i));
    target.push(point);
  });
  return { kept, keptText, lost, lostText };
}

/**
 * Objective space of one stored generation for 2 or 3 objectives.
 * Colour = role (Pₜ / Qₜ); filled = survived into Pₜ₊₁, open = discarded.
 */
export function objectiveSpaceTraces(
  snapshot: GenerationSnapshot,
  front: number[][] | null,
  layers: ReadonlySet<Layer>,
  theme: ChartTheme,
): Data[] {
  const nObj = snapshot.population.F[0]?.length ?? 2;
  const traces: Data[] = [];
  if (layers.has("front") && front) {
    traces.push(
      pointsTrace(front, nObj, {
        name: LAYER_LABELS.front,
        color: theme.reference,
        size: nObj === 2 ? 3 : 2,
      }),
    );
  }
  const groups: [Layer, SnapshotGroup | null | undefined, "P" | "Q", string][] = [
    ["population", snapshot.population, "P", seriesColor(theme, 0)],
    ["offspring", snapshot.offspring, "Q", seriesColor(theme, 1)],
  ];
  for (const [layer, group, role, color] of groups) {
    if (!group || !layers.has(layer)) continue;
    const { kept, keptText, lost, lostText } = split(group, role);
    traces.push(
      pointsTrace(kept, nObj, {
        name: `${LAYER_LABELS[layer]} · survived`,
        color,
        text: keptText,
        legendgroup: layer,
      }),
    );
    if (layers.has("discarded") && lost.length > 0) {
      traces.push(
        pointsTrace(lost, nObj, {
          name: `${LAYER_LABELS[layer]} · discarded`,
          color,
          open: true,
          text: lostText,
          legendgroup: layer,
        }),
      );
    }
  }
  return traces;
}

function parcoords(rows: number[][], codes: number[], colorscale: [number, string][]): Data {
  const nObj = rows[0]?.length ?? 0;
  return {
    type: "parcoords",
    line: { color: codes, cmin: 0, cmax: 1, colorscale },
    dimensions: Array.from({ length: nObj }, (_, i) => ({
      label: objectiveLabel(i),
      values: column(rows, i),
    })),
  } as Data;
}

/**
 * Many objectives: one polyline per individual. Colour = role; discarded
 * individuals are faint and drawn first so survivors stay readable on top.
 */
export function parallelCoordinatesTrace(
  snapshot: GenerationSnapshot,
  layers: ReadonlySet<Layer>,
  theme: ChartTheme,
): Data {
  // code / 3: 0 = Pt discarded, 1 = Qt discarded, 2 = Pt survived, 3 = Qt survived
  const buckets: number[][][] = [[], [], [], []];
  const add = (group: SnapshotGroup | null | undefined, role: number) => {
    if (!group) return;
    group.F.forEach((point, i) => {
      if (group.survived[i]) buckets[2 + role]?.push(point);
      else if (layers.has("discarded")) buckets[role]?.push(point);
    });
  };
  if (layers.has("population")) add(snapshot.population, 0);
  if (layers.has("offspring")) add(snapshot.offspring, 1);
  const rows = buckets.flat();
  const codes = buckets.flatMap((bucket, code) => bucket.map(() => code / 3));
  const [p, q] = [seriesColor(theme, 0), seriesColor(theme, 1)];
  return parcoords(rows, codes, [
    [0, withAlpha(p, 0.18)],
    [1 / 3, withAlpha(q, 0.18)],
    [2 / 3, withAlpha(p, 0.8)],
    [1, withAlpha(q, 0.8)],
  ]);
}

/** Live first front for many objectives. */
export function liveParallelTrace(points: number[][], theme: ChartTheme): Data {
  const color = withAlpha(seriesColor(theme, 0), 0.6);
  return parcoords(
    points,
    points.map(() => 0),
    [
      [0, color],
      [1, color],
    ],
  );
}

/** First front streamed while a run is in progress. */
export function liveFrontTraces(
  points: number[][],
  front: number[][] | null,
  showFront: boolean,
  theme: ChartTheme,
): Data[] {
  const nObj = points[0]?.length ?? front?.[0]?.length ?? 2;
  const traces: Data[] = [];
  if (showFront && front) {
    traces.push(
      pointsTrace(front, nObj, {
        name: LAYER_LABELS.front,
        color: theme.reference,
        size: nObj === 2 ? 3 : 2,
      }),
    );
  }
  traces.push(
    pointsTrace(points, nObj, { name: "Current first front", color: seriesColor(theme, 0) }),
  );
  return traces;
}

/** Median line with an interquartile band, optionally with every run in the background. */
export function convergenceTraces(
  summary: IndicatorSummary | undefined,
  runs: { label: string; series: MetricSeries }[],
  indicator: string,
  theme: ChartTheme,
  color: string = seriesColor(theme, 0),
  name = "Median",
): Data[] {
  const traces: Data[] = runs.map(({ label, series }, i) => ({
    type: "scatter",
    mode: "lines",
    name: "Individual runs",
    legendgroup: "runs",
    showlegend: i === 0,
    x: series.generation,
    y: series.values[indicator] ?? [],
    line: { color: withAlpha(theme.muted, 0.55), width: 1 },
    hovertemplate: `${label}<br>gen %{x}<br>%{y:.4g}<extra></extra>`,
  }));
  if (summary) traces.push(...bandTraces(summary, color, name));
  return traces;
}

export function bandTraces(summary: IndicatorSummary, color: string, name: string): Data[] {
  return [
    {
      type: "scatter",
      mode: "lines",
      x: summary.generation,
      y: summary.q3,
      line: { width: 0 },
      legendgroup: name,
      showlegend: false,
      hoverinfo: "skip",
    },
    {
      type: "scatter",
      mode: "lines",
      name: `${name} IQR`,
      legendgroup: name,
      x: summary.generation,
      y: summary.q1,
      fill: "tonexty",
      fillcolor: withAlpha(color, 0.18),
      line: { width: 0 },
      hoverinfo: "skip",
    },
    {
      type: "scatter",
      mode: "lines",
      name,
      legendgroup: name,
      x: summary.generation,
      y: summary.median,
      line: { color, width: 2 },
      customdata: summary.generation.map((_, i) => [
        summary.q1[i] ?? null,
        summary.q3[i] ?? null,
        summary.n_runs[i] ?? null,
      ]),
      hovertemplate: `${name}<br>gen %{x}<br>median %{y:.4g}<br>IQR [%{customdata[0]:.4g}, %{customdata[1]:.4g}]<br>%{customdata[2]} run(s)<extra></extra>`,
    },
  ];
}

export function baseLayout(theme: ChartTheme, overrides: Partial<Layout> = {}): Partial<Layout> {
  const axis = {
    gridcolor: theme.grid,
    linecolor: theme.axis,
    zerolinecolor: theme.axis,
    tickfont: { color: theme.muted },
    title: { font: { color: theme.inkSecondary } },
  };
  return {
    paper_bgcolor: theme.surface,
    plot_bgcolor: theme.surface,
    font: {
      family: "system-ui, -apple-system, 'Segoe UI', sans-serif",
      color: theme.ink,
      size: 12,
    },
    margin: { l: 56, r: 16, t: 16, b: 48 },
    legend: { orientation: "h", y: -0.18, font: { color: theme.inkSecondary } },
    hoverlabel: { bgcolor: theme.surface, bordercolor: theme.axis, font: { color: theme.ink } },
    xaxis: axis,
    yaxis: axis,
    ...overrides,
  };
}

/** Above this ratio between the x and y spans, equal scales would flatten the cloud into a line. */
export const EQUAL_SCALE_MAX_RATIO = 5;

/** Whether the 2D points of ``traces`` span comparable ranges on both axes. */
export function comparableSpans(traces: Data[]): boolean {
  const span = (key: "x" | "y") => {
    const values = traces.flatMap(
      (trace) => ((trace as { [k: string]: unknown })[key] as unknown[] | undefined) ?? [],
    );
    const numbers = values.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
    return numbers.length > 0 ? Math.max(...numbers) - Math.min(...numbers) : 0;
  };
  const [x, y] = [span("x"), span("y")];
  if (x === 0 || y === 0) return true;
  return Math.max(x, y) / Math.min(x, y) <= EQUAL_SCALE_MAX_RATIO;
}

export function objectiveSpaceLayout(
  theme: ChartTheme,
  nObj: number,
  revision: string,
  traces: Data[] = [],
): Partial<Layout> {
  const titled = (i: number) => ({
    title: { text: objectiveLabel(i), font: { color: theme.inkSecondary } },
  });
  const sceneAxis = (i: number) => ({
    ...titled(i),
    gridcolor: theme.grid,
    zerolinecolor: theme.axis,
    backgroundcolor: theme.surface,
    tickfont: { color: theme.muted },
  });
  const layout = baseLayout(theme, { uirevision: revision });
  if (nObj === 3) {
    return {
      ...layout,
      margin: { l: 0, r: 0, t: 0, b: 0 },
      legend: { ...layout.legend, y: 0 },
      scene: {
        xaxis: sceneAxis(0),
        yaxis: sceneAxis(1),
        zaxis: sceneAxis(2),
        aspectmode: "cube",
        camera: { eye: { x: 1.5, y: 1.5, z: 1.1 } },
      },
    };
  }
  if (!comparableSpans(traces)) {
    // e.g. ZDT4 early on: f2 spans hundreds while f1 stays in [0, 1]
    return {
      ...layout,
      xaxis: { ...layout.xaxis, ...titled(0) },
      yaxis: { ...layout.yaxis, ...titled(1) },
    };
  }
  return {
    ...layout,
    // Equal scales keep the geometry of the front; the plot area shrinks instead of the range.
    xaxis: { ...layout.xaxis, ...titled(0), constrain: "domain" },
    yaxis: { ...layout.yaxis, ...titled(1), scaleanchor: "x", constrain: "domain" },
  };
}
