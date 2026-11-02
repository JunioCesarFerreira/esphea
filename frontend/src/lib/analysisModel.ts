import type { Analysis } from "../api/types";
import { formatNumber } from "./format";
import { homologyLabel } from "./topologyPlots";

const CLOUD_LABELS = { survivors: "survivors", merged: "candidates", first_front: "first front" };
const NORMALIZATION_LABELS = { none: "raw", ideal_nadir: "ideal–nadir", min_max: "min–max" };

/** One-line summary of an analysis configuration. */
export function describeAnalysis(analysis: Analysis): string {
  const c = analysis.config;
  const homology = c.max_dimension === 0 ? "H₀" : `H₀–${homologyLabel(c.max_dimension)}`;
  return `${CLOUD_LABELS[c.point_cloud]} · ${NORMALIZATION_LABELS[c.normalization]} · ${homology} · ε ≤ ${formatNumber(c.max_epsilon)}`;
}
