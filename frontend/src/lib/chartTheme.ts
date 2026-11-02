/**
 * Chart colours per colour scheme.
 *
 * Categorical slots follow a palette validated for colour-vision deficiency
 * (light and dark steps validated separately). Scatter plots use at most the
 * first three slots; identity never relies on colour alone (marker fill and
 * legends add a second channel).
 */
export type Scheme = "light" | "dark";

export interface ChartTheme {
  surface: string;
  ink: string;
  inkSecondary: string;
  muted: string;
  grid: string;
  axis: string;
  /** Reference geometry (true Pareto front): neutral, never a series colour. */
  reference: string;
  series: readonly string[];
}

const LIGHT: ChartTheme = {
  surface: "#fcfcfb",
  ink: "#0b0b0b",
  inkSecondary: "#52514e",
  muted: "#898781",
  grid: "#e1e0d9",
  axis: "#c3c2b7",
  reference: "#b4b2aa",
  series: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
};

const DARK: ChartTheme = {
  surface: "#1a1a19",
  ink: "#f0efec",
  inkSecondary: "#c3c2b7",
  muted: "#898781",
  grid: "#2c2c2a",
  axis: "#383835",
  reference: "#5d5c57",
  series: ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"],
};

export function chartTheme(scheme: Scheme): ChartTheme {
  return scheme === "dark" ? DARK : LIGHT;
}

export function seriesColor(theme: ChartTheme, slot: number): string {
  return theme.series[slot % theme.series.length] ?? theme.ink;
}

/** ``#rrggbb`` -> ``rgba(r, g, b, alpha)``. */
export function withAlpha(hex: string, alpha: number): string {
  const value = Number.parseInt(hex.slice(1), 16);
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}
