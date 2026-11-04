import { Alert, Card, Group, SegmentedControl, Stack, Switch, Text } from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";
import { useMemo, useState } from "react";

import { useExperimentMetrics, useRunsMetrics } from "../../../api/queries";
import type { Experiment, MetricSeries } from "../../../api/types";
import { PlotlyChart } from "../../../components/PlotlyChart";
import { useChartTheme } from "../../../hooks/useChartTheme";
import { INDICATOR_LABELS, LOWER_IS_BETTER } from "../../../lib/configModel";
import { baseLayout, convergenceTraces } from "../../../lib/plots";

const INDICATOR_ORDER = Object.keys(INDICATOR_LABELS);

export function ConvergencePanel({ experiment, live }: { experiment: Experiment; live: boolean }) {
  const theme = useChartTheme();
  const summary = useExperimentMetrics(experiment.id, live);
  const runIds = useMemo(() => experiment.runs.map((run) => run.id), [experiment.runs]);
  const runs = useRunsMetrics(runIds, live);
  const indicators = INDICATOR_ORDER.filter((name) => name in (summary.data ?? {}));
  const [chosen, setChosen] = useState<string | null>(null);
  const indicator = chosen && indicators.includes(chosen) ? chosen : (indicators[0] ?? null);
  const [logScale, setLogScale] = useState(false);

  const runSeries = runs
    .map((query, i) => ({ label: `Run ${i + 1}`, series: query.data }))
    .filter(
      (entry): entry is { label: string; series: MetricSeries } => entry.series !== undefined,
    );

  if (!summary.isPending && indicators.length === 0) {
    return (
      <Alert icon={<IconInfoCircle size={16} />} color="gray">
        No indicator values yet.
      </Alert>
    );
  }
  if (!indicator) return null;

  const direction = LOWER_IS_BETTER[indicator] ? "lower is better" : "higher is better";
  const label = INDICATOR_LABELS[indicator] ?? indicator;
  return (
    <Stack gap="md">
      <Group justify="space-between">
        <SegmentedControl
          value={indicator}
          onChange={setChosen}
          data={indicators.map((name) => ({ value: name, label: INDICATOR_LABELS[name] ?? name }))}
        />
        <Switch
          label="Logarithmic scale"
          checked={logScale}
          onChange={(e) => setLogScale(e.currentTarget.checked)}
        />
      </Group>
      <Card withBorder padding="xs">
        <PlotlyChart
          ariaLabel={`${label} per generation`}
          height={460}
          data={convergenceTraces(summary.data?.[indicator], runSeries, indicator, theme)}
          layout={baseLayout(theme, {
            xaxis: { ...baseLayout(theme).xaxis, title: { text: "Generation" } },
            yaxis: {
              ...baseLayout(theme).yaxis,
              title: { text: `${label} (${direction})` },
              type: logScale ? "log" : "linear",
            },
            hovermode: "x",
          })}
        />
        <Text size="xs" c="dimmed" px="sm" pb="xs">
          Median across runs with the interquartile range; thin grey lines are the individual runs.
          Indicators are computed on the first front of each generation; the offspring hypervolume
          on the offspring Qₜ that produced it, with the same reference point.
        </Text>
      </Card>
    </Stack>
  );
}
