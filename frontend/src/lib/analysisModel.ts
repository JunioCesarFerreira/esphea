import type { Analysis, AnalysisConfig } from "../api/types";
import { formatNumber } from "./format";
import { homologyLabel } from "./topologyPlots";

const CLOUD_LABELS = { survivors: "survivors", merged: "candidates", first_front: "first front" };
const NORMALIZATION_LABELS = { none: "raw", ideal_nadir: "ideal–nadir", min_max: "min–max" };
const MIDDLE_LABELS = {
  rips: "",
  bridge_union: " · bridge over VR(Pₜ₋₁ ∪ Pₜ)",
  bridge: " · bridge over VR(Pₜ₋₁) ∪ VR(Pₜ)",
};

export const ANALYSIS_KIND_LABELS: Record<AnalysisConfig["kind"], string> = {
  topology: "Barcodes per generation",
  zigzag: "Zigzag across generations",
};

function homologyRange(maxDimension: number): string {
  return maxDimension === 0 ? "H₀" : `H₀–${homologyLabel(maxDimension)}`;
}

/** One-line summary of an analysis configuration. */
export function describeConfig(c: AnalysisConfig): string {
  const normalization = NORMALIZATION_LABELS[c.normalization ?? "none"];
  if (c.kind === "zigzag") {
    const scales = c.epsilons.map((e) => formatNumber(e)).join(", ");
    const middle = MIDDLE_LABELS[c.middle ?? "rips"];
    return `zigzag · ε ${scales} · ${homologyRange(c.max_dimension ?? 0)} · ${normalization}${middle}`;
  }
  return `${CLOUD_LABELS[c.point_cloud ?? "survivors"]} · ${normalization} · ${homologyRange(c.max_dimension ?? 1)} · ε ≤ ${formatNumber(c.max_epsilon)}`;
}

export function describeAnalysis(analysis: Analysis): string {
  const scope = analysis.config.kind === "zigzag" && analysis.batch_id ? " · all runs" : "";
  return describeConfig(analysis.config) + scope;
}
