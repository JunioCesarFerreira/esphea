import { Alert, Container, MultiSelect, Stack, Tabs, Title } from "@mantine/core";
import { IconChartLine, IconInfoCircle, IconTopologyStar3 } from "@tabler/icons-react";
import { useState } from "react";

import { useExperiments } from "../../api/queries";
import { QueryState } from "../../components/QueryState";
import { useChartTheme } from "../../hooks/useChartTheme";
import { seriesColor } from "../../lib/chartTheme";
import { ALGORITHM_LABELS } from "../../lib/configModel";
import { IndicatorComparison } from "./IndicatorComparison";
import { TopologyComparison } from "./TopologyComparison";

const MAX_SELECTED = 8; // number of validated categorical colour slots

/** An experiment in the comparison, with the colour it keeps while selected. */
export interface ComparedExperiment {
  id: string;
  name: string;
  color: string;
}

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

  const byId = new Map((experiments.data ?? []).map((e) => [e.id, e]));
  const options = (experiments.data ?? []).map((e) => ({
    value: e.id,
    label: `${e.name} · ${ALGORITHM_LABELS[e.algorithm as keyof typeof ALGORITHM_LABELS] ?? e.algorithm} · M=${e.n_obj}`,
  }));
  const compared: ComparedExperiment[] = selected.flatMap((id) => {
    const experiment = byId.get(id);
    return experiment
      ? [{ id, name: experiment.name, color: seriesColor(theme, slots[id] ?? 0) }]
      : [];
  });

  return (
    <Container size="xl">
      <Title order={2} mb="md">
        Compare experiments
      </Title>
      <QueryState isPending={experiments.isPending} error={experiments.error}>
        <Stack gap="md">
          <MultiSelect
            label="Experiments"
            placeholder="Pick up to eight experiments"
            data={options}
            value={selected}
            maxValues={MAX_SELECTED}
            searchable
            onChange={(ids) => {
              setSelected(ids);
              setSlots((previous) => assignSlots(previous, ids));
            }}
          />

          {compared.length === 0 ? (
            <Alert icon={<IconInfoCircle size={16} />} color="gray">
              Select experiments to compare the median and interquartile range of a quality
              indicator or of a topological summary across their runs.
            </Alert>
          ) : (
            <Tabs defaultValue="indicators" keepMounted={false}>
              <Tabs.List>
                <Tabs.Tab value="indicators" leftSection={<IconChartLine size={16} />}>
                  Indicators
                </Tabs.Tab>
                <Tabs.Tab value="topology" leftSection={<IconTopologyStar3 size={16} />}>
                  Topology
                </Tabs.Tab>
              </Tabs.List>
              <Tabs.Panel value="indicators" pt="md">
                <IndicatorComparison experiments={compared} />
              </Tabs.Panel>
              <Tabs.Panel value="topology" pt="md">
                <TopologyComparison experiments={compared} />
              </Tabs.Panel>
            </Tabs>
          )}
        </Stack>
      </QueryState>
    </Container>
  );
}
