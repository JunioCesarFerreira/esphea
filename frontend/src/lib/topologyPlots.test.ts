import { describe, expect, it } from "vitest";

import type { Diagram, TopologySeries } from "../api/types";
import { chartTheme } from "./chartTheme";
import {
  barcodeTraces,
  displayScale,
  bettiHeatmap,
  distanceTraces,
  homologyLabel,
  persistenceDiagramTraces,
} from "./topologyPlots";

const theme = chartTheme("light");

const diagram: Diagram = {
  generation: 3,
  max_epsilon: 2,
  dimensions: [
    { dimension: 0, birth: [0, 0, 0], death: [0.5, 2, 0.1], truncated: [false, true, false] },
    { dimension: 1, birth: [0.3], death: [0.6], truncated: [false] },
  ],
};

const series: TopologySeries = {
  generation: [0, 1, 2],
  n_points: [4, 4, 4],
  diameter: [3, 2, 1],
  hausdorff_previous: [null, 0.5, 0.2],
  hausdorff_final: [1, 0.4, 0],
  max_finite_death: 0.6,
  dimensions: [
    {
      dimension: 0,
      n_bars: [4, 4, 4],
      total_persistence: [1, 1, 1],
      persistent_entropy: [1, 1, 1],
      distances: { bottleneck: { previous: [null, 0.3, 0.1], final: [0.5, 0.2, 0] } },
    },
  ],
};

describe("barcodeTraces", () => {
  it("draws one segment per bar sorted by birth then length, with truncation markers", () => {
    const [h0, arrows, h1] = barcodeTraces(diagram, new Set([0, 1]), theme) as {
      x: (number | null)[];
      y: (number | null)[];
    }[];
    expect(h0?.x).toEqual([0, 2, null, 0, 0.5, null, 0, 0.1, null]);
    expect(h0?.y).toEqual([0, 0, null, 1, 1, null, 2, 2, null]);
    expect(arrows?.x).toEqual([2]);
    expect(h1?.y).toEqual([5, 5, null]); // H1 starts after a gap of two rows
  });

  it("clips truncated bars at the display edge", () => {
    const [h0, arrows] = barcodeTraces(diagram, new Set([0]), theme, 0.8) as {
      x: (number | null)[];
    }[];
    expect(h0?.x.slice(0, 2)).toEqual([0, 0.8]);
    expect(arrows?.x).toEqual([0.8]);
  });

  it("hides unselected dimensions", () => {
    expect(barcodeTraces(diagram, new Set([1]), theme)).toHaveLength(1);
  });
});

describe("persistenceDiagramTraces", () => {
  it("adds the diagonal and the truncation line before the points", () => {
    const traces = persistenceDiagramTraces(diagram, new Set([0]), theme);
    expect(traces.map((t) => t.name)).toEqual(["Diagonal", "alive at ε max", "H₀"]);
    const points = traces[2] as { marker: { symbol: string[] } };
    expect(points.marker.symbol).toEqual(["circle", "triangle-up", "circle"]);
  });
});

describe("distanceTraces", () => {
  it("pairs the bottleneck distance with twice the Hausdorff distance", () => {
    const traces = distanceTraces(series, 0, "bottleneck", "previous", theme) as {
      y: (number | null)[];
    }[];
    expect(traces[0]?.y).toEqual([null, 0.3, 0.1]);
    expect(traces[1]?.y).toEqual([null, 1, 0.4]);
  });

  it("has no stability bound for Wasserstein", () => {
    expect(distanceTraces(series, 0, "wasserstein_1", "final", theme)).toHaveLength(1);
  });
});

describe("bettiHeatmap", () => {
  it("puts generations on x and scales on y", () => {
    const [trace] = bettiHeatmap(
      {
        dimension: 0,
        epsilon: [0, 1],
        generation: [0, 1, 2],
        values: [
          [3, 1],
          [2, 1],
          [1, 1],
        ],
      },
      theme,
    ) as { z: number[][] }[];
    expect(trace?.z).toEqual([
      [3, 2, 1],
      [1, 1, 1],
    ]);
  });
});

it("labels homology dimensions", () => {
  expect(homologyLabel(1)).toBe("H₁");
});

it("chooses a display scale from the finite deaths", () => {
  expect(displayScale(1, 5)).toBeCloseTo(1.15);
  expect(displayScale(1, 1.1)).toBe(1.1);
  expect(displayScale(0, 2)).toBe(2);
});
