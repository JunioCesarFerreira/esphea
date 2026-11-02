/** Pure builders of persistent-homology charts (barcodes, diagrams, Betti curves, distances). */
import type { Data, Layout } from "plotly.js";

import type { BettiCurves, Diagram, DistanceMatrix, TopologySeries } from "../api/types";
import { seriesColor, withAlpha, type ChartTheme } from "./chartTheme";
import { baseLayout } from "./plots";

export const METRIC_LABELS: Record<string, string> = {
  bottleneck: "Bottleneck",
  wasserstein_1: "Wasserstein W₁",
};

export const SUMMARY_LABELS = {
  n_bars: "Number of bars",
  total_persistence: "Total persistence",
  persistent_entropy: "Persistent entropy",
} as const;

export type Summary = keyof typeof SUMMARY_LABELS;
export type Reference = "previous" | "final";

const SUBSCRIPTS = ["₀", "₁", "₂"];
export const homologyLabel = (dimension: number) => `H${SUBSCRIPTS[dimension] ?? dimension}`;

/** Single-hue sequential ramp; in dark mode low values recede towards the dark surface. */
function sequentialScale(theme: ChartTheme): [number, string][] {
  const ramp = ["#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"];
  const steps = theme.surface === "#1a1a19" ? [...ramp].reverse() : ramp;
  return steps.map((color, i) => [i / (steps.length - 1), color]);
}

/**
 * Upper end of the displayed scale: a little beyond the largest finite death of
 * the whole analysis (stable across generations), never beyond ε max. Features
 * still alive at ε max are drawn at this edge.
 */
export function displayScale(maxFiniteDeath: number, maxEpsilon: number): number {
  return maxFiniteDeath > 0 ? Math.min(maxEpsilon, maxFiniteDeath * 1.15) : maxEpsilon;
}

interface BarRow {
  birth: number;
  death: number;
  truncated: boolean;
}

/**
 * One horizontal segment per bar, grouped by homology dimension and sorted by
 * birth then length, longest first. Truncated bars end with an arrow head.
 */
export function barcodeTraces(
  diagram: Diagram,
  dimensions: ReadonlySet<number>,
  theme: ChartTheme,
  edge: number = diagram.max_epsilon,
): Data[] {
  const traces: Data[] = [];
  let offset = 0;
  for (const bars of diagram.dimensions) {
    if (!dimensions.has(bars.dimension)) continue;
    const rows: BarRow[] = bars.birth
      .map((birth, i) => ({
        birth,
        death: bars.death[i] ?? birth,
        truncated: bars.truncated[i] ?? false,
      }))
      .sort((a, b) => a.birth - b.birth || b.death - b.birth - (a.death - a.birth));
    const color = seriesColor(theme, bars.dimension);
    const label = homologyLabel(bars.dimension);
    const describe = (row: BarRow) =>
      `${label}: [${row.birth.toPrecision(4)}, ${row.truncated ? "≥ " : ""}${row.death.toPrecision(4)}]`;
    // Segments separated by nulls: (birth, i) -> (death, i), gap, ...
    traces.push({
      type: "scattergl",
      mode: "lines",
      name: label,
      legendgroup: label,
      x: rows.flatMap((row) => [row.birth, row.truncated ? edge : row.death, null]),
      y: rows.flatMap((_, i) => [offset + i, offset + i, null]),
      text: rows.flatMap((row) => [describe(row), describe(row), ""]),
      hoverinfo: "text",
      line: { color, width: 2 },
    });
    const truncated = rows.flatMap((row, i) => (row.truncated ? [{ row, y: offset + i }] : []));
    if (truncated.length > 0) {
      traces.push({
        type: "scattergl",
        mode: "markers",
        name: `${label} alive at ε max`,
        legendgroup: label,
        showlegend: false,
        x: truncated.map(() => edge),
        y: truncated.map(({ y }) => y),
        marker: { symbol: "triangle-right", size: 8, color },
        hoverinfo: "skip",
      });
    }
    offset += rows.length + 2;
  }
  return traces;
}

export function barcodeLayout(theme: ChartTheme, edge: number): Partial<Layout> {
  const layout = baseLayout(theme);
  return {
    ...layout,
    hovermode: "closest",
    xaxis: { ...layout.xaxis, title: { text: "ε (edge length)" }, range: [0, edge * 1.03] },
    yaxis: { ...layout.yaxis, showticklabels: false, showgrid: false, title: { text: "bars" } },
  };
}

/**
 * Birth-death scatter with the diagonal. Features alive at ε max are drawn as
 * triangles on a line at the top edge of the displayed scale.
 */
export function persistenceDiagramTraces(
  diagram: Diagram,
  dimensions: ReadonlySet<number>,
  theme: ChartTheme,
  edge: number = diagram.max_epsilon,
): Data[] {
  const max = edge;
  const traces: Data[] = [
    {
      type: "scatter",
      mode: "lines",
      name: "Diagonal",
      x: [0, max],
      y: [0, max],
      line: { color: theme.axis, width: 1 },
      hoverinfo: "skip",
      showlegend: false,
    },
    {
      type: "scatter",
      mode: "lines",
      name: "alive at ε max",
      x: [0, max],
      y: [max, max],
      line: { color: theme.muted, width: 1 },
      hoverinfo: "skip",
      showlegend: false,
    },
  ];
  for (const bars of diagram.dimensions) {
    if (!dimensions.has(bars.dimension)) continue;
    const label = homologyLabel(bars.dimension);
    traces.push({
      type: "scattergl",
      mode: "markers",
      name: label,
      x: bars.birth,
      y: bars.death.map((death, i) => (bars.truncated[i] ? edge : death)),
      customdata: bars.death.map((death, i) =>
        bars.truncated[i] ? `≥ ${death.toPrecision(4)} (ε max)` : death.toPrecision(4),
      ),
      marker: {
        color: seriesColor(theme, bars.dimension),
        size: 8,
        symbol: bars.truncated.map((t) => (t ? "triangle-up" : "circle")),
        line: { color: theme.surface, width: 1 },
      },
      hovertemplate: `${label}<br>birth %{x:.4g}<br>death %{customdata}<extra></extra>`,
    });
  }
  return traces;
}

export function persistenceDiagramLayout(theme: ChartTheme, edge: number): Partial<Layout> {
  const layout = baseLayout(theme);
  const range = [0, edge * 1.05];
  return {
    ...layout,
    xaxis: { ...layout.xaxis, title: { text: "birth" }, range, constrain: "domain" },
    yaxis: {
      ...layout.yaxis,
      title: { text: "death" },
      range,
      scaleanchor: "x",
      constrain: "domain",
    },
  };
}

/** Distance between the diagram of each generation and a reference, per one metric. */
export function distanceTraces(
  series: TopologySeries,
  dimension: number,
  metric: string,
  reference: Reference,
  theme: ChartTheme,
): Data[] {
  const dim = series.dimensions.find((d) => d.dimension === dimension);
  const distances = dim?.distances[metric]?.[reference] ?? [];
  const traces: Data[] = [
    {
      type: "scatter",
      mode: "lines",
      name: `${METRIC_LABELS[metric] ?? metric} (${homologyLabel(dimension)})`,
      x: series.generation,
      y: distances,
      line: { color: seriesColor(theme, dimension), width: 2 },
      hovertemplate: "generation %{x}<br>%{y:.4g}<extra></extra>",
    },
  ];
  if (metric === "bottleneck") {
    const hausdorff = reference === "previous" ? series.hausdorff_previous : series.hausdorff_final;
    traces.push({
      type: "scatter",
      mode: "lines",
      name: "2 × Hausdorff (stability bound)",
      x: series.generation,
      y: hausdorff.map((value) => (value === null ? null : 2 * value)),
      line: { color: withAlpha(theme.muted, 0.9), width: 1.5 },
      hovertemplate: "generation %{x}<br>2·d_H %{y:.4g}<extra></extra>",
    });
  }
  return traces;
}

export function summaryTraces(series: TopologySeries, summary: Summary, theme: ChartTheme): Data[] {
  return series.dimensions.map((dim) => ({
    type: "scatter",
    mode: "lines",
    name: homologyLabel(dim.dimension),
    x: series.generation,
    y: dim[summary],
    line: { color: seriesColor(theme, dim.dimension), width: 2 },
    hovertemplate: `${homologyLabel(dim.dimension)}<br>generation %{x}<br>%{y:.4g}<extra></extra>`,
  }));
}

/** Betti numbers over generation (x) and scale (y). */
export function bettiHeatmap(betti: BettiCurves, theme: ChartTheme): Data[] {
  const transposed = betti.epsilon.map((_, j) => betti.values.map((row) => row[j] ?? 0));
  return [
    {
      type: "heatmap",
      x: betti.generation,
      y: betti.epsilon,
      z: transposed,
      colorscale: sequentialScale(theme),
      colorbar: { title: { text: `β${SUBSCRIPTS[betti.dimension] ?? ""}` }, outlinewidth: 0 },
      hovertemplate: `generation %{x}<br>ε %{y:.4g}<br>β = %{z}<extra></extra>`,
    } as Data,
  ];
}

export function matrixHeatmap(matrix: DistanceMatrix, theme: ChartTheme): Data[] {
  return [
    {
      type: "heatmap",
      x: matrix.generation,
      y: matrix.generation,
      z: matrix.values,
      colorscale: sequentialScale(theme),
      colorbar: { title: { text: METRIC_LABELS[matrix.metric] ?? matrix.metric }, outlinewidth: 0 },
      hovertemplate: "generations %{x} × %{y}<br>%{z:.4g}<extra></extra>",
    } as Data,
  ];
}

export function generationLayout(
  theme: ChartTheme,
  yTitle: string,
  overrides: Partial<Layout> = {},
): Partial<Layout> {
  const layout = baseLayout(theme);
  return {
    ...layout,
    hovermode: "x",
    xaxis: { ...layout.xaxis, title: { text: "Generation" } },
    yaxis: { ...layout.yaxis, title: { text: yTitle } },
    ...overrides,
  };
}
