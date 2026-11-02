import { Center, Loader } from "@mantine/core";
import type * as PlotlyApi from "plotly.js";
import type { Config, Data, Layout } from "plotly.js";
import { useEffect, useRef, useState } from "react";

type PlotlyModule = typeof PlotlyApi;

// Plotly is large: load it once, on demand, so pages without charts stay light.
// It is a CommonJS bundle, hence the default export.
let plotlyPromise: Promise<PlotlyModule> | null = null;
const loadPlotly = () =>
  (plotlyPromise ??= import("plotly.js-dist-min").then((module) => module.default));

const CONFIG: Partial<Config> = {
  displaylogo: false,
  responsive: true,
  modeBarButtonsToRemove: ["select2d", "lasso2d", "toggleSpikelines"],
  toImageButtonOptions: { format: "svg", filename: "esphea-chart" },
};

interface PlotlyChartProps {
  data: Data[];
  layout: Partial<Layout>;
  height?: number;
  ariaLabel: string;
}

/** Thin imperative wrapper: ``Plotly.react`` on every change, ``purge`` on unmount. */
export function PlotlyChart({ data, layout, height = 480, ariaLabel }: PlotlyChartProps) {
  const container = useRef<HTMLDivElement>(null);
  const [plotly, setPlotly] = useState<PlotlyModule | null>(null);

  useEffect(() => {
    let active = true;
    void loadPlotly().then((module) => active && setPlotly(() => module));
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const element = container.current;
    if (!plotly || !element) return;
    void plotly.react(element, data, { ...layout, height, autosize: true }, CONFIG);
  }, [plotly, data, layout, height]);

  useEffect(() => {
    const element = container.current;
    if (!plotly || !element) return;
    const observer = new ResizeObserver(() => void plotly.Plots.resize(element));
    observer.observe(element);
    return () => {
      observer.disconnect();
      plotly.purge(element);
    };
  }, [plotly]);

  return (
    <div role="img" aria-label={ariaLabel} style={{ width: "100%", minHeight: height }}>
      {!plotly && (
        <Center h={height}>
          <Loader size="sm" />
        </Center>
      )}
      <div ref={container} style={{ width: "100%" }} />
    </div>
  );
}
