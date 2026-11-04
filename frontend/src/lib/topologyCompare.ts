import type { AnalysisConfig, AnalysisGroup, AnalysisGroupSummary } from "../api/types";
import { formatNumber } from "./format";
import { METRIC_LABELS, SUMMARY_LABELS } from "./topologyPlots";

export type AnalysisKind = AnalysisConfig["kind"];

export interface Quantity {
  label: string;
  /** Counted per generation (births, deaths): runs are compared by their total. */
  event: boolean;
}

const distanceQuantities = (): Record<string, Quantity> =>
  Object.fromEntries(
    Object.entries(METRIC_LABELS).flatMap(([metric, label]) => [
      [`${metric}_previous`, { label: `${label} to the previous generation`, event: false }],
      [`${metric}_final`, { label: `${label} to the final generation`, event: false }],
    ]),
  );

/** What can be compared, per kind of analysis (keys of the group summary's series). */
export const QUANTITIES: Record<AnalysisKind, Record<string, Quantity>> = {
  topology: {
    ...Object.fromEntries(
      Object.entries(SUMMARY_LABELS).map(([name, label]) => [name, { label, event: false }]),
    ),
    ...distanceQuantities(),
  },
  zigzag: {
    betti: { label: "Betti number at Pₜ", event: false },
    births: { label: "Births", event: true },
    births_variation: { label: "Births · variation", event: true },
    births_selection: { label: "Births · selection", event: true },
    deaths: { label: "Deaths", event: true },
    deaths_variation: { label: "Deaths · variation", event: true },
    deaths_selection: { label: "Deaths · selection", event: true },
  },
};

export const DEFAULT_QUANTITY: Record<AnalysisKind, string> = {
  topology: "total_persistence",
  zigzag: "betti",
};

const ofKind = (groups: AnalysisGroup[], kind: AnalysisKind) =>
  groups.filter((g) => g.config.kind === kind);

/**
 * Group shown for each experiment unless the user picks one: the configuration
 * shared by most experiments (so they are comparable), then the one with most
 * completed runs, then the newest.
 */
export function defaultGroupKeys(
  groupsByExperiment: Record<string, AnalysisGroup[]>,
  kind: AnalysisKind,
): Record<string, string | null> {
  const shared = new Map<string, number>();
  for (const groups of Object.values(groupsByExperiment)) {
    for (const g of ofKind(groups, kind)) shared.set(g.key, (shared.get(g.key) ?? 0) + 1);
  }
  const better = (a: AnalysisGroup, b: AnalysisGroup) => {
    const sharedA = shared.get(a.key) ?? 0;
    const sharedB = shared.get(b.key) ?? 0;
    if (sharedA !== sharedB) return sharedA > sharedB;
    if (a.runs !== b.runs) return a.runs > b.runs;
    return Date.parse(a.created_at) > Date.parse(b.created_at);
  };
  return Object.fromEntries(
    Object.entries(groupsByExperiment).map(([id, groups]) => {
      const best = ofKind(groups, kind).reduce<AnalysisGroup | null>(
        (top, g) => (top === null || better(g, top) ? g : top),
        null,
      );
      return [id, best?.key ?? null];
    }),
  );
}

/**
 * Settings that differ between the analyses being compared and change the
 * scale of their series; empty when the comparison is like for like.
 */
export function differingSettings(configs: AnalysisConfig[], epsilonIndex: number): string[] {
  if (configs.length < 2) return [];
  const differs = (value: (c: AnalysisConfig) => unknown) =>
    new Set(configs.map((c) => JSON.stringify(value(c)))).size > 1;
  const settings: string[] = [];
  if (differs((c) => c.normalization ?? "none")) settings.push("normalisation");
  if (differs((c) => (c.kind === "topology" ? (c.point_cloud ?? "survivors") : null))) {
    settings.push("point cloud");
  }
  if (differs((c) => (c.kind === "topology" ? c.max_epsilon : c.epsilons[epsilonIndex]))) {
    settings.push("scale ε");
  }
  return settings;
}

const defaultMaxDimension = (c: AnalysisConfig) => c.max_dimension ?? (c.kind === "zigzag" ? 0 : 1);

/** Homology dimensions computed by every analysis being compared. */
export function commonDimensions(configs: AnalysisConfig[]): number[] {
  if (configs.length === 0) return [0];
  const highest = Math.min(...configs.map(defaultMaxDimension));
  return Array.from({ length: highest + 1 }, (_, k) => k);
}

/** Zigzag scales by position, labelled by their value when every analysis shares it. */
export function scaleOptions(configs: AnalysisConfig[]): { value: string; label: string }[] {
  const zigzags = configs.filter((c) => c.kind === "zigzag");
  if (zigzags.length === 0) return [];
  const count = Math.min(...zigzags.map((c) => c.epsilons.length));
  return Array.from({ length: count }, (_, i) => {
    const values = new Set(zigzags.map((c) => c.epsilons[i]));
    const [only] = values;
    return {
      value: String(i),
      label: values.size === 1 && only !== undefined ? `ε ${formatNumber(only)}` : `scale ${i + 1}`,
    };
  });
}

/** The value each experiment is ranked by in the table, with its spread. */
export function tableValue(
  summary: AnalysisGroupSummary,
  quantity: string,
): { median: number; q1: number; q3: number } | null {
  if (QUANTITIES.zigzag[quantity]?.event) return summary.totals[quantity] ?? null;
  const series = summary.series[quantity];
  if (!series) return null;
  for (let i = series.median.length - 1; i >= 0; i -= 1) {
    const [median, q1, q3] = [series.median[i], series.q1[i], series.q3[i]];
    if (median != null && q1 != null && q3 != null) return { median, q1, q3 };
  }
  return null;
}
