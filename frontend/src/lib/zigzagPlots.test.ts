import { describe, expect, it } from "vitest";

import type { Representative, ZigzagBars, ZigzagEvents } from "../api/types";
import { chartTheme } from "./chartTheme";
import {
  barRows,
  batchTraces,
  representativeTraces,
  stepLabel,
  stepX,
  zigzagBarcodeTraces,
  zigzagEventTraces,
} from "./zigzagPlots";

const theme = chartTheme("light");

const bars: ZigzagBars = {
  epsilon: 0.2,
  dimension: 0,
  n_generations: 3,
  n_steps: 7,
  n_simplices: 100,
  representatives_skipped: null,
  bar: [0, 1, 2],
  birth: [0, 3, 1],
  death: [7, 4, 6],
  kind: ["cc", "oo", "co"],
  birth_cause: ["initial", "variation", "variation"],
  death_cause: ["end", "selection", "selection"],
  representative: [true, null, false],
};

describe("steps", () => {
  it("places R_t half a generation before P_t", () => {
    expect(stepX(4)).toBe(2);
    expect(stepX(3)).toBe(1.5);
    expect(stepLabel(4)).toBe("P₂");
    expect(stepLabel(3)).toBe("R₂");
    expect(stepLabel(0)).toBe("P₀");
  });
});

describe("zigzagBarcodeTraces", () => {
  it("sorts bars by birth and colours them by the cause of birth", () => {
    expect(barRows(bars).map((r) => r.bar)).toEqual([0, 2, 1]);
    const traces = zigzagBarcodeTraces(bars, theme, null);
    const names = traces.map((t) => t.name);
    expect(names).toContain("Born by initial population");
    expect(names).toContain("Born by variation (offspring)");
    expect(names).toContain("Alive at the end");
    expect(names).toContain("Dies by selection (removal)");
    const initial = traces[0] as { x: (number | null)[] };
    expect(initial.x).toEqual([-0.25, 3.25, null]); // steps 0..6 -> generations 0..3
  });

  it("highlights the selected bar", () => {
    const traces = zigzagBarcodeTraces(bars, theme, 2);
    const last = traces.at(-1) as { name: string; y: number[] };
    expect(last.name).toBe("Selected bar");
    expect(last.y).toEqual([1, 1]);
  });
});

describe("zigzagEventTraces", () => {
  it("draws births upwards and deaths downwards", () => {
    const events: ZigzagEvents = {
      epsilon: 0.2,
      dimension: 0,
      generation: [0, 1],
      betti_p: [3, 2],
      betti_r: [null, 4],
      births_variation: [0, 2],
      births_selection: [0, 1],
      deaths_variation: [0, 1],
      deaths_selection: [0, 3],
    };
    const [bv, , , ds] = zigzagEventTraces(events, theme) as { y: number[] }[];
    expect(bv?.y).toEqual([0, 2]);
    expect(ds?.y).toEqual([-0, -3]);
  });
});

describe("representativeTraces", () => {
  it("draws the population, the niche and the cycle edges", () => {
    const view: Representative = {
      step: 2,
      generation: 1,
      is_r_step: false,
      dimension: 1,
      members: [10, 11, 12, 13],
      points: [
        [0, 0],
        [1, 0],
        [0, 1],
        [5, 5],
      ],
      simplices: [
        [10, 11],
        [11, 12],
        [10, 12],
      ],
      component: [],
    };
    const traces = representativeTraces(view, theme);
    expect(traces.map((t) => t.name)).toEqual([
      "Population at P₁",
      "Representative cycle",
      "Representative vertices",
    ]);
    const cycle = traces[1] as { x: (number | null)[] };
    expect(cycle.x).toHaveLength(9); // three edges, two points and a gap each
  });
});

describe("batchTraces", () => {
  it("shows the median and IQR of the series of a view", () => {
    const summary = {
      generation: [0, 1],
      n_runs: 3,
      series: { births_variation: { q1: [0, 1], median: [0, 2], q3: [0, 3] } },
    };
    expect(batchTraces(summary, "births", theme).map((t) => t.name)).toEqual([
      undefined,
      "Births · variation IQR",
      "Births · variation",
    ]);
  });
});
