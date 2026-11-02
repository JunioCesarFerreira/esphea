import { describe, expect, it } from "vitest";

import type { GenerationSnapshot, SnapshotGroup } from "../api/types";
import { chartTheme } from "./chartTheme";
import { formatBytes, formatNumber } from "./format";
import { bandTraces, objectiveSpaceTraces, parallelCoordinatesTrace, type Layer } from "./plots";

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
