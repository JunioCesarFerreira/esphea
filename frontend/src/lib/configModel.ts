/** Pure helpers for editing an experiment configuration. */
import type {
  AlgorithmConfig,
  AlgorithmName,
  Catalog,
  ExperimentConfig,
  ValidationIssue,
} from "../api/types";

export const ALGORITHM_LABELS: Record<AlgorithmName, string> = {
  nsga2: "NSGA-II",
  nsga3: "NSGA-III",
};

export const PROBLEM_LABELS: Record<string, string> = { dtlz2: "DTLZ2" };

export const INDICATOR_LABELS: Record<string, string> = {
  igd: "IGD",
  igd_plus: "IGD+",
  hv: "Hypervolume",
};

/** Whether lower values of an indicator are better. */
export const LOWER_IS_BETTER: Record<string, boolean> = { igd: true, igd_plus: true, hv: false };

export function describeExperiment(config: ExperimentConfig): string {
  const problem = PROBLEM_LABELS[config.problem.name] ?? config.problem.name;
  return `${ALGORITHM_LABELS[config.algorithm.name]} on ${problem} (M=${config.problem.n_obj})`;
}

export function algorithmDefaults(catalog: Catalog, name: AlgorithmName): AlgorithmConfig {
  const found = catalog.algorithms.find((algorithm) => algorithm.name === name);
  if (!found) throw new Error(`algorithm '${name}' is not in the catalog`);
  return structuredClone(found);
}

export function defaultConfig(
  catalog: Catalog,
  algorithm: AlgorithmName = "nsga3",
): ExperimentConfig {
  const problem = catalog.problems[0];
  if (!problem) throw new Error("the catalog has no problems");
  const config: ExperimentConfig = {
    name: "",
    problem: structuredClone(problem),
    algorithm: algorithmDefaults(catalog, algorithm),
    n_gen: 250,
    n_runs: 5,
    seed: 1,
    metrics: structuredClone(catalog.metrics),
    snapshots: structuredClone(catalog.snapshots),
  };
  return { ...config, name: describeExperiment(config) };
}

/** Swap the algorithm for the defaults of another one, keeping everything else. */
export function switchAlgorithm(
  config: ExperimentConfig,
  catalog: Catalog,
  name: AlgorithmName,
): ExperimentConfig {
  if (config.algorithm.name === name) return config;
  const wasGenerated = config.name === describeExperiment(config);
  const next = { ...config, algorithm: algorithmDefaults(catalog, name) };
  return wasGenerated ? { ...next, name: describeExperiment(next) } : next;
}

export function duplicateConfig(config: ExperimentConfig): ExperimentConfig {
  return { ...structuredClone(config), name: `${config.name} (copy)` };
}

/**
 * Index server validation issues by dotted field path relative to the body
 * (e.g. ``algorithm.nsga3.pop_size`` -> ``algorithm.pop_size``). Model-level
 * issues land under the empty path.
 */
export function issuesByPath(issues: ValidationIssue[]): Map<string, string[]> {
  const result = new Map<string, string[]>();
  for (const issue of issues) {
    const path = issue.loc
      .slice(1)
      .filter((part) => !(typeof part === "string" && ["nsga2", "nsga3"].includes(part)))
      .join(".");
    const message = issue.msg.replace(/^Value error, /, "");
    result.set(path, [...(result.get(path) ?? []), message]);
  }
  return result;
}
