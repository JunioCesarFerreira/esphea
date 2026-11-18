import { describe, expect, it } from "vitest";

import type { GenerationSnapshot, SnapshotGroup } from "../api/types";
import { chartTheme } from "./chartTheme";
import { formatBytes, formatNumber } from "./format";
import {
  hyperplaneCoordinates,
  projectSnapshot,
  bandTraces,
  comparableSpans,
  objectiveSpaceLayout,
  objectiveSpaceTraces,
  parallelCoordinatesTrace,
  type Layer,
} from "./plots";

const theme = chartTheme("light");

function group(F: number[][], survived: boolean[]): SnapshotGroup {
  return {
    F,
    X: null,
    survived,
    rank: survived.map((s) => (s ? 0 : -1)),
    times_selected: F.map(() => 1),
    parents: F.map(() => [0, 1]),
    mutated: F.map(() => false),
  };
}

const snapshot: GenerationSnapshot = {
  run_id: "r",
  generation: 3,
  population: group(
    [
      [0, 1],
      [1, 0],
    ],
    [true, false],
  ),
  offspring: group(
    [
      [0.5, 0.5],
      [0.9, 0.9],
    ],
    [true, false],
  ),
};

const all = new Set<Layer>(["population", "offspring", "discarded", "front"]);

describe("objectiveSpaceTraces", () => {
  it("splits each role into survived (filled) and discarded (open) traces", () => {
    const traces = objectiveSpaceTraces(snapshot, [[0, 1]], all, theme);
    expect(traces.map((t) => t.name)).toEqual([
      "True front",
      "Parents Pₜ · survived",
      "Parents Pₜ · discarded",
      "Offspring Qₜ · survived",
      "Offspring Qₜ · discarded",
    ]);
    const discarded = traces[2] as { marker: { color: string; line: { color: string } } };
    expect(discarded.marker.color).toBe("rgba(0,0,0,0)");
    expect(discarded.marker.line.color).toBe(theme.series[0]);
  });

  it("honours hidden layers", () => {
    const traces = objectiveSpaceTraces(snapshot, null, new Set<Layer>(["offspring"]), theme);
    expect(traces.map((t) => t.name)).toEqual(["Offspring Qₜ · survived"]);
  });

  it("uses 3D scatter for three objectives", () => {
    const three: GenerationSnapshot = {
      ...snapshot,
      population: group([[0, 0, 1]], [true]),
      offspring: null,
    };
    expect(objectiveSpaceTraces(three, null, all, theme)[0]?.type).toBe("scatter3d");
  });
});

describe("parallelCoordinatesTrace", () => {
  it("keeps one polyline per visible individual", () => {
    const trace = parallelCoordinatesTrace(
      snapshot,
      new Set<Layer>(["population", "offspring"]),
      theme,
    ) as {
      dimensions: { values: number[] }[];
    };
    expect(trace.dimensions).toHaveLength(2);
    // survivors are drawn last (on top): Pt survivor, then Qt survivor
    expect(trace.dimensions[0]?.values).toEqual([0, 0.5]);
  });
});

describe("bandTraces", () => {
  it("draws q3, q1 (filled to q3) and the median", () => {
    const traces = bandTraces(
      { generation: [0, 1], median: [2, 1], q1: [1.5, 0.5], q3: [2.5, 1.5], n_runs: [3, 3] },
      "#2a78d6",
      "NSGA-III",
    );
    expect(traces.map((t) => (t as { fill?: string }).fill)).toEqual([
      undefined,
      "tonexty",
      undefined,
    ]);
    expect(traces[2]?.name).toBe("NSGA-III");
  });
});

describe("format", () => {
  it("formats bytes and numbers", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
    expect(formatNumber(0.053412)).toBe("0.05341");
    expect(formatNumber(null)).toBe("—");
  });
});

describe("objective space scales", () => {
  const cloud = (x: number[], y: number[]) => [{ type: "scattergl" as const, x, y }];

  it("keeps equal scales when both objectives span similar ranges", () => {
    const traces = cloud([0, 0.5, 1], [0, 0.8, 1.2]);
    expect(comparableSpans(traces)).toBe(true);
    expect(objectiveSpaceLayout(theme, 2, "r", traces).yaxis?.scaleanchor).toBe("x");
  });

  it("frees the scales when one objective spans far more than the other", () => {
    const traces = cloud([0, 0.3, 1], [90, 150, 230]); // ZDT4 at generation 0
    expect(comparableSpans(traces)).toBe(false);
    expect(objectiveSpaceLayout(theme, 2, "r", traces).yaxis?.scaleanchor).toBeUndefined();
  });

  it("ignores gaps and degenerate clouds", () => {
    expect(comparableSpans(cloud([0, NaN, 1], [0, 1, 2]))).toBe(true);
    expect(comparableSpans([])).toBe(true);
  });
});

describe("hyperplane projection", () => {
  it("uses the Helmert basis of the backend's TOPO problems", () => {
    // u_1 = (f_1 − f_2)/√2, u_2 = (f_1 + f_2 − 2 f_3)/√6, u_3 = (f_1 + f_2 + f_3 − 3 f_4)/√12
    const [u] = hyperplaneCoordinates([[1, 0, 0, 0]]);
    expect(u?.[0]).toBeCloseTo(1 / Math.SQRT2);
    expect(u?.[1]).toBeCloseTo(1 / Math.sqrt(6));
    expect(u?.[2]).toBeCloseTo(1 / Math.sqrt(12));
    // the direction (1, 1, 1, 1) is dropped
    expect(hyperplaneCoordinates([[0.5, 0.5, 0.5, 0.5]])[0]).toEqual([0, 0, 0]);
  });

  it("keeps distances within the hyperplane", () => {
    const a = [0.2, 0.6, 0.5, 0.7];
    const b = [0.4, 0.3, 0.8, 0.5]; // both sum to 2
    const [ua, ub] = hyperplaneCoordinates([a, b]);
    const distance = (p: number[], q: number[]) =>
      Math.hypot(...p.map((value, i) => value - (q[i] ?? 0)));
    expect(distance(ua ?? [], ub ?? [])).toBeCloseTo(distance(a, b));
  });

  it("projects every group of a snapshot", () => {
    const four = group(
      [
        [0.5, 0.5, 0.5, 0.5],
        [1, 0, 0, 0],
      ],
      [true, false],
    );
    const projected = projectSnapshot({ ...snapshot, population: four, offspring: four });
    expect(projected.population.F[0]).toEqual([0, 0, 0]);
    expect(projected.offspring?.F[1]).toHaveLength(3);
    expect(projected.population.survived).toEqual([true, false]);
  });
});
