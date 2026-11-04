import {
  Card,
  ColorSwatch,
  Group,
  SegmentedControl,
  Stack,
  Switch,
  Table,
  Text,
} from "@mantine/core";
import { useState } from "react";

import { useExperimentsMetrics } from "../../api/queries";
import { PlotlyChart } from "../../components/PlotlyChart";
import { useChartTheme } from "../../hooks/useChartTheme";
import { INDICATOR_LABELS, LOWER_IS_BETTER } from "../../lib/configModel";
import { formatNumber } from "../../lib/format";
import { bandTraces, baseLayout } from "../../lib/plots";
import type { ComparedExperiment } from "./ComparePage";

/** Median and interquartile range of a quality indicator across each experiment's runs. */
export function IndicatorComparison({ experiments }: { experiments: ComparedExperiment[] }) {
  const theme = useChartTheme();
  const [indicator, setIndicator] = useState("igd");
  const [logScale, setLogScale] = useState(false);
  const metrics = useExperimentsMetrics(experiments.map((e) => e.id));

  const series = experiments.flatMap((experiment, i) => {
    const summary = metrics[i]?.data?.[indicator];
    return summary ? [{ ...experiment, summary }] : [];
  });

  const label = INDICATOR_LABELS[indicator] ?? indicator;
  const axis = baseLayout(theme);
  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="wrap">
        <SegmentedControl
          value={indicator}
          onChange={setIndicator}
          data={Object.entries(INDICATOR_LABELS).map(([value, text]) => ({
            value,
            label: text,
          }))}
        />
        <Switch
          label="Log scale"
          checked={logScale}
          onChange={(e) => setLogScale(e.currentTarget.checked)}
        />
      </Group>
      <Card withBorder padding="xs">
        <PlotlyChart
          ariaLabel={`${label} per generation for the selected experiments`}
          height={480}
          data={series.flatMap((s) => bandTraces(s.summary, s.color, s.name))}
          layout={baseLayout(theme, {
            xaxis: { ...axis.xaxis, title: { text: "Generation" } },
            yaxis: {
              ...axis.yaxis,
              title: {
                text: `${label} (${LOWER_IS_BETTER[indicator] ? "lower" : "higher"} is better)`,
              },
              type: logScale ? "log" : "linear",
            },
            hovermode: "x",
          })}
        />
      </Card>
      <Card withBorder padding={0}>
        <Table verticalSpacing="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Experiment</Table.Th>
              <Table.Th ta="right">Runs</Table.Th>
              <Table.Th ta="right">Final median {label}</Table.Th>
              <Table.Th ta="right">IQR</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {series.map((s) => (
              <Table.Tr key={s.id}>
                <Table.Td>
                  <Group gap="xs" wrap="nowrap">
                    <ColorSwatch color={s.color} size={12} />
                    <Text size="sm">{s.name}</Text>
                  </Group>
                </Table.Td>
                <Table.Td ta="right" className="tabular">
                  {s.summary.n_runs.at(-1) ?? 0}
                </Table.Td>
                <Table.Td ta="right" className="tabular">
                  {formatNumber(s.summary.median.at(-1))}
                </Table.Td>
                <Table.Td ta="right" className="tabular">
                  [{formatNumber(s.summary.q1.at(-1))}, {formatNumber(s.summary.q3.at(-1))}]
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Card>
    </Stack>
  );
}
