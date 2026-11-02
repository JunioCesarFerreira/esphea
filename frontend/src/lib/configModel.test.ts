import { describe, expect, it } from "vitest";

import type { Catalog } from "../api/types";
import {
  defaultConfig,
  describeExperiment,
  duplicateConfig,
  issuesByPath,
  switchAlgorithm,
} from "./configModel";

const catalog: Catalog = {
  problems: [{ name: "dtlz2", n_obj: 3, k: 10 }],
  algorithms: [
    {
      name: "nsga2",
      pop_size: 100,
      crossover: { eta: 15, prob: 0.9, prob_var: 0.5 },
      mutation: { eta: 20, prob_var: null },
    },
    {
      name: "nsga3",
      n_partitions: 12,
      pop_size: null,
      crossover: { eta: 30, prob: 1, prob_var: 0.5 },
      mutation: { eta: 20, prob_var: null },
    },
  ],
  metrics: { igd: true, igd_plus: true, hv: true, every: 1, reference_front_size: 1000 },
  snapshots: { enabled: true, every: 1, precision: "float64", decision_variables: true },
};

describe("configModel", () => {
  it("builds a default configuration with a descriptive name", () => {
    const config = defaultConfig(catalog);
    expect(config.algorithm.name).toBe("nsga3");
    expect(config.name).toBe("NSGA-III on DTLZ2 (M=3)");
  });

  it("does not share objects with the catalog", () => {
    const config = defaultConfig(catalog);
    config.problem.n_obj = 5;
    expect(catalog.problems[0]?.n_obj).toBe(3);
  });

  it("switches algorithm and renames generated names only", () => {
    const generated = switchAlgorithm(defaultConfig(catalog), catalog, "nsga2");
    expect(generated.algorithm).toEqual(catalog.algorithms[0]);
    expect(generated.name).toBe(describeExperiment(generated));

    const custom = { ...defaultConfig(catalog), name: "My study" };
    expect(switchAlgorithm(custom, catalog, "nsga2").name).toBe("My study");
  });

  it("duplicates with a copy suffix", () => {
    const copy = duplicateConfig({ ...defaultConfig(catalog), name: "A" });
    expect(copy.name).toBe("A (copy)");
  });

  it("indexes validation issues by field path", () => {
    const issues = issuesByPath([
      { loc: ["body", "algorithm", "nsga3", "pop_size"], msg: "too small", type: "x" },
      { loc: ["body"], msg: "Value error, pop_size below directions", type: "value_error" },
    ]);
    expect(issues.get("algorithm.pop_size")).toEqual(["too small"]);
    expect(issues.get("")).toEqual(["pop_size below directions"]);
  });
});
