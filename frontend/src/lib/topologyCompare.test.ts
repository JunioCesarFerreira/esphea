import { describe, expect, it } from "vitest";

import type { AnalysisConfig, AnalysisGroup, AnalysisGroupSummary } from "../api/types";
import {
  commonDimensions,
  defaultGroupKeys,
  differingSettings,
  scaleOptions,
  tableValue,
} from "./topologyCompare";

const topology = (overrides: Partial<AnalysisConfig> = {}): AnalysisConfig => ({
  kind: "topology",
  point_cloud: "survivors",
  normalization: "ideal_nadir",
  max_dimension: 1,
  max_epsilon: 0.2,
  distance_matrix: false,
  ...(overrides as object),
});

const zigzag = (epsilons: number[], overrides: object = {}): AnalysisConfig => ({
  kind: "zigzag",
  epsilons,
  max_dimension: 0,
  normalization: "ideal_nadir",
  middle: "rips",
  representatives: 10,
  ...overrides,
});

const group = (
  key: string,
  config: AnalysisConfig,
  runs = 2,
  created_at = "2026-11-01T00:00:00Z",
): AnalysisGroup => ({
  key,
  kind: config.kind,
  config,
  analysis_ids: [],
  runs,
  pending: 0,
  created_at,
});

describe("defaultGroupKeys", () => {
  it("prefers the configuration shared by most experiments", () => {
    const keys = defaultGroupKeys(
      {
        a: [group("own", topology(), 5, "2026-11-03T00:00:00Z"), group("shared", topology())],
        b: [group("shared", topology())],
        c: [group("other", zigzag([0.1]))],
      },
      "topology",
    );
    expect(keys).toEqual({ a: "shared", b: "shared", c: null });
  });

  it("then the most complete, then the newest group", () => {
    const keys = defaultGroupKeys(
      {
        a: [
          group("old", topology(), 3, "2026-11-01T00:00:00Z"),
          group("new", topology(), 3, "2026-11-02T00:00:00Z"),
          group("few", topology(), 1, "2026-11-03T00:00:00Z"),
        ],
      },
      "topology",
    );
    expect(keys.a).toBe("new");
  });
});

describe("differingSettings", () => {
  it("is empty for a like-for-like comparison", () => {
    expect(differingSettings([topology(), topology({ distance_matrix: true })], 0)).toEqual([]);
  });

  it("names the settings that change the scale of the series", () => {
    expect(
      differingSettings([topology(), topology({ normalization: "none", max_epsilon: 1 })], 0),
    ).toEqual(["normalisation", "scale ε"]);
  });

  it("compares zigzag scales at the chosen position only", () => {
    const configs = [zigzag([0.1, 0.2]), zigzag([0.1, 0.3])];
    expect(differingSettings(configs, 0)).toEqual([]);
    expect(differingSettings(configs, 1)).toEqual(["scale ε"]);
  });

  it("names the complex at R_t only above H0, where the bridge changes the barcode", () => {
    const configs = [zigzag([0.1]), zigzag([0.1], { middle: "bridge" })];
    expect(differingSettings(configs, 0, 0)).toEqual([]);
    expect(differingSettings(configs, 0, 1)).toEqual(["complex at Rₜ"]);
  });
});

describe("commonDimensions and scaleOptions", () => {
  it("keep what every analysis computed", () => {
    expect(commonDimensions([topology(), topology({ max_dimension: 2 })])).toEqual([0, 1]);
    expect(commonDimensions([zigzag([0.1]), topology()])).toEqual([0]);
    expect(scaleOptions([zigzag([0.1, 0.2]), zigzag([0.1, 0.3, 0.4])])).toEqual([
      { value: "0", label: "ε 0.1" },
      { value: "1", label: "scale 2" },
    ]);
  });
});

describe("tableValue", () => {
  const summary: AnalysisGroupSummary = {
    kind: "zigzag",
    generation: [0, 1, 2],
    n_runs: [2, 2, 1],
    series: {
      betti: { q1: [1, 2, null], median: [1, 3, null], q3: [1, 4, null] },
    },
    totals: { births: { q1: 10, median: 12, q3: 14 } },
  };

  it("uses the last generation with a value for states", () => {
    expect(tableValue(summary, "betti")).toEqual({ median: 3, q1: 2, q3: 4 });
  });

  it("uses the per-run total for events", () => {
    expect(tableValue(summary, "births")).toEqual({ median: 12, q1: 10, q3: 14 });
    expect(tableValue(summary, "deaths")).toBeNull();
  });
});
