import { describe, expect, it } from "vitest";

import type { MethodSummary, TrackerBars, TrackerRuns } from "../api/types";
import { chartTheme } from "./chartTheme";
import {
  a12,
  atLeastTraces,
  direction,
  experimentBoxTraces,
  formatShare,
  methodBoxTraces,
  methodColor,
  quartiles,
  trackerBarcodeTraces,
  trackerRows,
} from "./trackerModel";

const theme = chartTheme("light");

const bars: TrackerBars = {
  epsilon: 0.1,
  method: "t2",
  n_generations: 3,
  n_steps: 7,
  birth: [2, 0, 0],
  death: [4, 7, 2],
  matched_step: [false, true, false],
  matched_generation: [true, true, false],
};

const summary = (method: string, atLeast: number[]): MethodSummary => ({
  method,
  n_bars: atLeast[0] ?? 0,
  n_long: 0,
  median_lifetime: null,
  p90_lifetime: null,
  agreement_step: null,
  agreement_generation: null,
  long_agreement_step: null,
  long_agreement_generation: null,
  at_least: atLeast,
});

const runs = (values: Record<string, (number | null)[]>): TrackerRuns => ({
  epsilon: 0.1,
  long_lifetime: 50,
  n_runs: 3,
  skipped: 0,
  methods: Object.fromEntries(
    Object.entries(values).map(([method, n_long]) => [
      method,
      {
        n_bars: n_long,
        n_long,
        median_lifetime: n_long,
        p90_lifetime: n_long,
        agreement_step: n_long,
        agreement_generation: n_long,
        long_agreement_step: n_long,
        long_agreement_generation: n_long,
      },
    ]),
  ),
});

describe("tracker barcode", () => {
  it("orders bars by birth, longest first", () => {
    const rows = trackerRows(bars, "step");
    expect(rows.map((r) => [r.birth, r.death])).toEqual([
      [0, 7],
      [0, 2],
      [2, 4],
    ]);
    expect(rows.map((r) => r.matched)).toEqual([true, false, false]);
    expect(trackerRows(bars, "generation").map((r) => r.matched)).toEqual([true, false, true]);
  });

  it("greys the bars the zigzag also has and colours the others", () => {
    const traces = trackerBarcodeTraces(bars, "step", theme) as {
      name: string;
      y: (number | null)[];
      line: { color: string };
    }[];
    expect(traces.map((t) => t.name)).toEqual(["Same bar in the zigzag", "Not in the zigzag"]);
    expect(traces[0]?.line.color).toBe(theme.reference);
    expect(traces[1]?.line.color).toBe(methodColor(theme, "t2"));
    expect(traces[1]?.y).toEqual([1, 1, null, 2, 2, null]);
  });
});

describe("bars alive at least L steps", () => {
  it("leaves zero counts out of the log axis", () => {
    const [zigzag, t1] = atLeastTraces(
      [summary("zigzag", [3, 2, 0, 0]), summary("t1", [3, 1, 1, 1])],
      theme,
    ) as { x: number[]; y: number[]; line: { color: string } }[];
    expect(zigzag?.x).toEqual([1, 2]);
    expect(zigzag?.y).toEqual([3, 2]);
    expect(zigzag?.line.color).toBe(theme.ink);
    expect(t1?.x).toEqual([1, 2, 3, 4]);
  });
});

describe("statistics across runs", () => {
  it("computes quartiles like numpy, ignoring missing values", () => {
    expect(quartiles([4, null, 1, 3, 2])).toEqual({ q1: 1.75, median: 2.5, q3: 3.25, n: 4 });
    expect(quartiles([null])).toBeNull();
  });

  it("computes Vargha-Delaney A12 with ties counting half", () => {
    expect(a12([3, 4], [1, 2])).toBe(1);
    expect(a12([1, 2], [3, 4])).toBe(0);
    expect(a12([1, 2], [1, 2])).toBe(0.5);
    expect(a12([2], [1, 2, 3])).toBe(0.5);
    expect(a12([], [1])).toBeNull();
  });

  it("reads the direction of an effect", () => {
    expect(direction(0.9)).toBe("higher");
    expect(direction(0.5)).toBe("similar");
    expect(direction(0.3)).toBe("lower");
    expect(direction(null)).toBeNull();
  });

  it("formats shares as percentages", () => {
    expect(formatShare(0.8834)).toBe("88.3%");
    expect(formatShare(null)).toBe("—");
  });
});

describe("box plots", () => {
  it("draws one box per method, skipping methods without values", () => {
    const traces = methodBoxTraces(runs({ zigzag: [1, 2], t1: [null], t2: [3] }), "n_long", theme);
    expect(traces.map((t) => t.name)).toEqual(["Zigzag", "T2"]);
  });

  it("groups the experiments' boxes by method", () => {
    const [trace] = experimentBoxTraces(
      [{ name: "A", color: "#000000", runs: runs({ zigzag: [1, 2], t1: [3] }) }],
      "n_long",
    ) as { x: string[]; y: number[] }[];
    expect(trace?.x).toEqual(["Zigzag", "Zigzag", "T1"]);
    expect(trace?.y).toEqual([1, 2, 3]);
  });
});
