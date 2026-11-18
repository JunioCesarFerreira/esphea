/** Pure helpers for editing an experiment configuration. */
import type {
  AlgorithmConfig,
  AlgorithmName,
  Catalog,
  ExperimentConfig,
  ProblemConfig,
  ProblemName,
  ShapeName,
  TOPOConfig,
  ValidationIssue,
} from "../api/types";

export const ALGORITHM_LABELS: Record<AlgorithmName, string> = {
  nsga2: "NSGA-II",
  nsga3: "NSGA-III",
  smsemoa: "SMS-EMOA",
};

export const PROBLEM_LABELS: Record<string, string> = {
  dtlz1: "DTLZ1",
  dtlz2: "DTLZ2",
  dtlz2h: "DTLZ2-H",
  dtlz5: "DTLZ5",
  dtlz7: "DTLZ7",
  zdt1: "ZDT1",
  zdt2: "ZDT2",
  zdt3: "ZDT3",
  zdt4: "ZDT4",
  zdt6: "ZDT6",
  imop4: "IMOP4",
  imop5: "IMOP5",
  imop6: "IMOP6",
  imop7: "IMOP7",
  imop8: "IMOP8",
  topo: "TOPO",
};

const IMOP = "Three objectives (Tian et al., 2019), solutions crowded very unevenly";

export const PROBLEM_DESCRIPTIONS: Record<ProblemName, string> = {
  dtlz1:
    "Scalable number of objectives; a linear front (the simplex Σf = 0.5) behind 11^k − 1 local fronts.",
  dtlz2: "Scalable number of objectives; the front is a sphere octant.",
  dtlz2h:
    "Three objectives; the DTLZ2 octant with a dominated cap at its centre, so the front has one hole.",
  dtlz5: "Three objectives; a degenerate front: one arc of the unit sphere (a curve).",
  dtlz7: "Scalable number of objectives; front split into 2^(M−1) disconnected pieces.",
  zdt1: "Bi-objective; convex, connected front.",
  zdt2: "Bi-objective; concave, connected front.",
  zdt3: "Bi-objective; front split into five disconnected pieces.",
  zdt4: "Bi-objective; convex front hidden behind many local fronts (multimodal).",
  zdt6: "Bi-objective; concave front, with solutions crowded towards one of its ends.",
  imop4: `${IMOP}; a degenerate front: a wavy curve.`,
  imop5: `${IMOP}; eight disjoint discs on a plane (8 pieces).`,
  imop6: `${IMOP}; a grid of strips on a plane: one piece with nine holes.`,
  imop7: `${IMOP}; three bands of the sphere that meet at its centre (a star, no holes).`,
  imop8: `${IMOP}; a 10 × 10 array of disconnected patches (100 pieces).`,
  topo: "A front drawn on the hyperplane Σf = M/2 with a chosen shape, so its topology is known exactly (a platform construction).",
};

/** Problems of the benchmark selector, by family. */
export const PROBLEM_GROUPS: { group: string; names: ProblemName[] }[] = [
  { group: "DTLZ", names: ["dtlz1", "dtlz2", "dtlz2h", "dtlz5", "dtlz7"] },
  { group: "ZDT · two objectives", names: ["zdt1", "zdt2", "zdt3", "zdt4", "zdt6"] },
  { group: "IMOP · irregular fronts", names: ["imop4", "imop5", "imop6", "imop7", "imop8"] },
  { group: "Prescribed topology", names: ["topo"] },
];

interface ShapeInfo {
  label: string;
  n_obj: 3 | 4;
  description: string;
  /** Smallest, largest and default count, for the shapes that take one. */
  count?: [number, number, number];
}

/** Shapes of the TOPO front; their Betti numbers come from ``topoBetti``. */
export const TOPO_SHAPES: Record<ShapeName, ShapeInfo> = {
  disc: { label: "Disc", n_obj: 3, description: "A disc: the contractible control." },
  ring: { label: "Ring", n_obj: 3, description: "A circle: a one-dimensional loop." },
  eight: { label: "Figure eight", n_obj: 3, description: "Two circles touching at a point." },
  holes: {
    label: "Disc with holes",
    n_obj: 3,
    description: "A disc with round holes of radius 0.1.",
    count: [1, 6, 2],
  },
  islands: { label: "Islands", n_obj: 3, description: "Disjoint discs.", count: [2, 8, 4] },
  ball: { label: "Ball", n_obj: 4, description: "A solid ball: the control in four objectives." },
  shell: { label: "Shell", n_obj: 4, description: "A ball with a cavity (a void)." },
  sphere: { label: "Sphere", n_obj: 4, description: "The surface of a ball." },
  torus: { label: "Torus", n_obj: 4, description: "The surface of a torus." },
};

/** Betti numbers (β₀, β₁, …) of a TOPO front. */
export function topoBetti(shape: ShapeName, count: number | null): number[] {
  const k = count ?? 0;
  const betti: Record<ShapeName, number[]> = {
    disc: [1, 0],
    ring: [1, 1],
    eight: [1, 2],
    holes: [1, k],
    islands: [k, 0],
    ball: [1, 0, 0],
    shell: [1, 0, 1],
    sphere: [1, 0, 1],
    torus: [1, 2, 1],
  };
  return betti[shape];
}

/** Change the shape of a TOPO problem, with its number of objectives and count. */
export function switchShape(problem: TOPOConfig, shape: ShapeName): TOPOConfig {
  const info = TOPO_SHAPES[shape];
  const count = info.count
    ? Math.min(Math.max(problem.count ?? info.count[2], info.count[0]), info.count[1])
    : null;
  return { ...problem, shape, n_obj: info.n_obj, count };
}

/** Short name of a configured problem, e.g. "DTLZ2" or "TOPO-holes2". */
export function problemLabel(problem: ProblemConfig): string {
  if (problem.name === "topo") return `TOPO-${problem.shape}${problem.count ?? ""}`;
  return PROBLEM_LABELS[problem.name] ?? problem.name;
}

export const INDICATOR_LABELS: Record<string, string> = {
  igd: "IGD",
  igd_plus: "IGD+",
  gd: "GD",
  hv: "Hypervolume",
  hv_offspring: "Offspring HV",
  spacing: "Spacing",
  spread: "Spread Δ",
  mean_distance: "Mean distance",
  decision_inertia: "Decision inertia",
};

/** Quality indicators measure the front against the true one; diversity metrics describe the population. */
export const INDICATOR_GROUPS: { group: string; names: string[] }[] = [
  { group: "Quality", names: ["igd", "igd_plus", "gd", "hv", "hv_offspring"] },
  { group: "Diversity", names: ["spacing", "spread", "mean_distance", "decision_inertia"] },
];

/** Whether lower values are better; absent for metrics that only describe the population. */
export const LOWER_IS_BETTER: Record<string, boolean> = {
  igd: true,
  igd_plus: true,
  gd: true,
  hv: false,
  hv_offspring: false,
  spacing: true,
  spread: true,
};

/** Axis title of a metric: its label and, when it has one, the better direction. */
export function indicatorAxisTitle(name: string): string {
  const label = INDICATOR_LABELS[name] ?? name;
  const lower = LOWER_IS_BETTER[name];
  if (lower === undefined) return label;
  return `${label} (${lower ? "lower" : "higher"} is better)`;
}

/** Select options of the metrics present in ``available``, grouped and in display order. */
export function indicatorOptions(
  available: string[],
): { group: string; items: { value: string; label: string }[] }[] {
  return INDICATOR_GROUPS.map(({ group, names }) => ({
    group,
    items: names
      .filter((name) => available.includes(name))
      .map((name) => ({ value: name, label: INDICATOR_LABELS[name] ?? name })),
  })).filter((g) => g.items.length > 0);
}

export function describeExperiment(config: ExperimentConfig): string {
  const problem = problemLabel(config.problem);
  return `${ALGORITHM_LABELS[config.algorithm.name]} on ${problem} (M=${config.problem.n_obj})`;
}

/** Replace the problem; a name generated from the old one follows the change. */
export function withProblem(config: ExperimentConfig, problem: ProblemConfig): ExperimentConfig {
  const wasGenerated = config.name === describeExperiment(config);
  const next = { ...config, problem };
  return wasGenerated ? { ...next, name: describeExperiment(next) } : next;
}

export function algorithmDefaults(catalog: Catalog, name: AlgorithmName): AlgorithmConfig {
  const found = catalog.algorithms.find((algorithm) => algorithm.name === name);
  if (!found) throw new Error(`algorithm '${name}' is not in the catalog`);
  return structuredClone(found);
}

export function problemDefaults(catalog: Catalog, name: ProblemName): ProblemConfig {
  const found = catalog.problems.find((problem) => problem.name === name);
  if (!found) throw new Error(`problem '${name}' is not in the catalog`);
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

/** Swap the problem for the defaults of another one, keeping everything else. */
export function switchProblem(
  config: ExperimentConfig,
  catalog: Catalog,
  name: ProblemName,
): ExperimentConfig {
  if (config.problem.name === name) return config;
  return withProblem(config, problemDefaults(catalog, name));
}

export function duplicateConfig(config: ExperimentConfig): ExperimentConfig {
  return { ...structuredClone(config), name: `${config.name} (copy)` };
}

/** Tags of the discriminated unions, which the server inserts into issue paths. */
const UNION_TAGS = new Set([...Object.keys(ALGORITHM_LABELS), ...Object.keys(PROBLEM_LABELS)]);

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
      .filter((part) => !(typeof part === "string" && UNION_TAGS.has(part)))
      .join(".");
    const message = issue.msg.replace(/^Value error, /, "");
    result.set(path, [...(result.get(path) ?? []), message]);
  }
  return result;
}
