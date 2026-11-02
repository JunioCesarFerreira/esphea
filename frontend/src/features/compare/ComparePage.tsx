import {
  Alert,
  Card,
  ColorSwatch,
  Container,
  Group,
  MultiSelect,
  SegmentedControl,
  Stack,
  Switch,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";
import { useState } from "react";

import { useExperiments, useExperimentsMetrics } from "../../api/queries";
import { PlotlyChart } from "../../components/PlotlyChart";
import { QueryState } from "../../components/QueryState";
import { useChartTheme } from "../../hooks/useChartTheme";
import { seriesColor } from "../../lib/chartTheme";
import { ALGORITHM_LABELS, INDICATOR_LABELS, LOWER_IS_BETTER } from "../../lib/configModel";
import { formatNumber } from "../../lib/format";
import { bandTraces, baseLayout } from "../../lib/plots";

const MAX_SELECTED = 8; // number of validated categorical colour slots

/**
 * Colour follows the experiment, not its position: a slot is assigned when an
 * experiment is selected and kept while it stays selected.
 */
function assignSlots(previous: Record<string, number>, selected: string[]): Record<string, number> {
  const next: Record<string, number> = {};
  for (const id of selected) {
    const slot = previous[id];
    if (slot !== undefined) next[id] = slot;
  }
  const used = new Set(Object.values(next));
  for (const id of selected) {
    if (id in next) continue;
    let slot = 0;
    while (used.has(slot)) slot += 1;
    next[id] = slot;
    used.add(slot);
  }
  return next;
}

export function ComparePage() {
  const theme = useChartTheme();
  const experiments = useExperiments();
  const [selected, setSelected] = useState<string[]>([]);
  const [slots, setSlots] = useState<Record<string, number>>({});
  const [indicator, setIndicator] = useState("igd");
  const [logScale, setLogScale] = useState(false);
  const metrics = useExperimentsMetrics(selected);

  const byId = new Map((experiments.data ?? []).map((e) => [e.id, e]));
  const options = (experiments.data ?? []).map((e) => ({
    value: e.id,
    label: `${e.name} · ${ALGORITHM_LABELS[e.algorithm as keyof typeof ALGORITHM_LABELS] ?? e.algorithm} · M=${e.n_obj}`,
  }));

  const series = selected.flatMap((id, i) => {
    const summary = metrics[i]?.data?.[indicator];
    const experiment = byId.get(id);
    if (!summary || !experiment) return [];
    return [{ id, name: experiment.name, color: seriesColor(theme, slots[id] ?? 0), summary }];
  });

  const label = INDICATOR_LABELS[indicator] ?? indicator;
  const axis = baseLayout(theme);
  return (
    <Container size="xl">
      <Title order={2} mb="md">
        Compare experiments
      </Title>
      <QueryState isPending={experiments.isPending} error={experiments.error}>
        <Stack gap="md">
          <Group align="flex-end" wrap="wrap">
            <MultiSelect
              label="Experiments"
              placeholder="Pick up to eight experiments"
              data={options}
              value={selected}
              maxValues={MAX_SELECTED}
              searchable
              style={{ flex: 1, minWidth: 320 }}
              onChange={(ids) => {
                setSelected(ids);
                setSlots((previous) => assignSlots(previous, ids));
              }}
            />
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

          {selected.length === 0 ? (
            <Alert icon={<IconInfoCircle size={16} />} color="gray">
              Select experiments to compare the median and interquartile range of an indicator
              across their runs.
            </Alert>
          ) : (
            <>
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
            </>
          )}
        </Stack>
      </QueryState>
    </Container>
  );
}
