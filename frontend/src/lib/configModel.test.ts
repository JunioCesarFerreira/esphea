import { describe, expect, it } from "vitest";

import type { Catalog, ProblemName, TOPOConfig } from "../api/types";
import {
  indicatorAxisTitle,
  indicatorOptions,
  defaultConfig,
  describeExperiment,
  duplicateConfig,
  issuesByPath,
  PROBLEM_DESCRIPTIONS,
  PROBLEM_GROUPS,
  PROBLEM_LABELS,
  problemLabel,
  switchAlgorithm,
  switchProblem,
  switchShape,
  TOPO_SHAPES,
  topoBetti,
  withProblem,
} from "./configModel";

const catalog: Catalog = {
  problems: [
    { name: "dtlz2", n_obj: 3, k: 10 },
    { name: "zdt1", n_obj: 2, n_var: 30 },
    { name: "zdt4", n_obj: 2, n_var: 10 },
    { name: "topo", shape: "holes", count: 2, n_obj: 3, k: 10 },
  ],
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
  metrics: {
    gd: true,
    igd: true,
    igd_plus: true,
    hv: true,
    hv_offspring: true,
    diversity: true,
    every: 1,
    reference_front_size: 1000,
  },
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

  it("switches problem to its defaults and renames generated names only", () => {
    const generated = switchProblem(defaultConfig(catalog), catalog, "zdt4");
    expect(generated.problem).toEqual({ name: "zdt4", n_obj: 2, n_var: 10 });
    expect(generated.name).toBe("NSGA-III on ZDT4 (M=2)");
    expect(generated.algorithm).toEqual(defaultConfig(catalog).algorithm);

    const custom = { ...defaultConfig(catalog), name: "My study" };
    expect(switchProblem(custom, catalog, "zdt1").name).toBe("My study");
  });

  it("duplicates with a copy suffix", () => {
    const copy = duplicateConfig({ ...defaultConfig(catalog), name: "A" });
    expect(copy.name).toBe("A (copy)");
  });

  it("indexes validation issues by field path", () => {
    const issues = issuesByPath([
      { loc: ["body", "algorithm", "nsga3", "pop_size"], msg: "too small", type: "x" },
      { loc: ["body"], msg: "Value error, pop_size below directions", type: "value_error" },
      { loc: ["body", "problem", "zdt1", "n_var"], msg: "too few", type: "x" },
    ]);
    expect(issues.get("problem.n_var")).toEqual(["too few"]);
    expect(issues.get("algorithm.pop_size")).toEqual(["too small"]);
    expect(issues.get("")).toEqual(["pop_size below directions"]);
  });
});

describe("indicator options", () => {
  it("group the available metrics and only give a direction where one exists", () => {
    expect(indicatorOptions(["hv", "spacing", "igd", "unknown"])).toEqual([
      {
        group: "Quality",
        items: [
          { value: "igd", label: "IGD" },
          { value: "hv", label: "Hypervolume" },
        ],
      },
      { group: "Diversity", items: [{ value: "spacing", label: "Spacing" }] },
    ]);
    expect(indicatorAxisTitle("hv")).toBe("Hypervolume (higher is better)");
    expect(indicatorAxisTitle("mean_distance")).toBe("Mean distance");
  });
});

describe("problems", () => {
  const topo: TOPOConfig = { name: "topo", shape: "holes", count: 2, n_obj: 3, k: 10 };

  it("are all labelled, described and listed once in the selector", () => {
    const listed = PROBLEM_GROUPS.flatMap((group) => group.names);
    expect(new Set(listed).size).toBe(listed.length);
    expect(new Set(listed)).toEqual(new Set(Object.keys(PROBLEM_LABELS)));
    for (const name of listed) expect(PROBLEM_DESCRIPTIONS[name as ProblemName]).toBeTruthy();
  });

  it("name TOPO fronts by their shape", () => {
    expect(problemLabel(topo)).toBe("TOPO-holes2");
    expect(problemLabel({ ...topo, shape: "torus", count: null, n_obj: 4 })).toBe("TOPO-torus");
    expect(problemLabel({ name: "dtlz1", n_obj: 3, k: 5 })).toBe("DTLZ1");
  });

  it("switch shapes with their objectives and counts", () => {
    expect(switchShape(topo, "torus")).toEqual({ ...topo, shape: "torus", count: null, n_obj: 4 });
    expect(switchShape(topo, "islands")).toMatchObject({ count: 2, n_obj: 3 });
    expect(switchShape({ ...topo, count: 6 }, "islands").count).toBe(6);
    expect(switchShape({ ...topo, shape: "ring", count: null }, "islands").count).toBe(4);
    expect(switchShape({ ...topo, shape: "islands", count: 8 }, "holes").count).toBe(6);
  });

  it("know the Betti numbers of every shape", () => {
    expect(topoBetti("holes", 3)).toEqual([1, 3]);
    expect(topoBetti("islands", 5)).toEqual([5, 0]);
    expect(topoBetti("torus", null)).toEqual([1, 2, 1]);
    for (const [shape, info] of Object.entries(TOPO_SHAPES)) {
      // planar shapes have β₀, β₁; spatial ones β₀, β₁, β₂
      expect(topoBetti(shape as keyof typeof TOPO_SHAPES, 2)).toHaveLength(info.n_obj - 1);
    }
  });

  it("rename a generated experiment when the problem changes", () => {
    const config = switchProblem(defaultConfig(catalog), catalog, "topo");
    expect(config.name).toBe("NSGA-III on TOPO-holes2 (M=3)");
    const torus = withProblem(config, switchShape(topo, "torus"));
    expect(torus.name).toBe("NSGA-III on TOPO-torus (M=4)");
    const custom = withProblem({ ...config, name: "Mine" }, switchShape(topo, "ring"));
    expect(custom.name).toBe("Mine");
  });
});
