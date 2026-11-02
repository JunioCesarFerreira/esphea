import { useComputedColorScheme } from "@mantine/core";

import { chartTheme, type ChartTheme } from "../lib/chartTheme";

export function useChartTheme(): ChartTheme {
  return chartTheme(useComputedColorScheme("light"));
}
