import { ActionIcon, Card, Progress, Table, Text, Tooltip } from "@mantine/core";
import { IconDownload } from "@tabler/icons-react";
import { useMemo } from "react";

import { useRunsMetrics } from "../../../api/queries";
import type { Experiment } from "../../../api/types";
import { StatusBadge } from "../../../components/StatusBadge";
import { INDICATOR_LABELS } from "../../../lib/configModel";
import { formatDuration, formatNumber, secondsBetween } from "../../../lib/format";

const INDICATORS = ["igd", "igd_plus", "hv"] as const;

export function RunsPanel({ experiment, live }: { experiment: Experiment; live: boolean }) {
  const runIds = useMemo(() => experiment.runs.map((run) => run.id), [experiment.runs]);
  const metrics = useRunsMetrics(runIds, live);
  return (
    <Card withBorder padding={0}>
      <Table.ScrollContainer minWidth={820}>
        <Table verticalSpacing="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Run</Table.Th>
              <Table.Th>Seed</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Generation</Table.Th>
              <Table.Th>Duration</Table.Th>
              {INDICATORS.map((name) => (
                <Table.Th key={name} ta="right">
                  Final {INDICATOR_LABELS[name]}
                </Table.Th>
              ))}
              <Table.Th aria-label="Download" />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {experiment.runs.map((run, i) => {
              const values = metrics[i]?.data?.values ?? {};
              const last = (name: string) => values[name]?.at(-1) ?? null;
              const seconds = secondsBetween(run.started_at ?? null, run.finished_at ?? null);
              return (
                <Table.Tr key={run.id}>
                  <Table.Td>{run.index + 1}</Table.Td>
                  <Table.Td className="tabular">{run.seed}</Table.Td>
                  <Table.Td>
                    <StatusBadge status={run.status} />
                    {run.attempt > 1 && (
                      <Text size="xs" c="dimmed" mt={4}>
                        Attempt {run.attempt}
                      </Text>
                    )}
                    {run.error && (
                      <Text
                        size="xs"
                        c={run.status === "failed" ? "red" : "dimmed"}
                        mt={4}
                        maw={260}
                        lineClamp={2}
                        title={run.error}
                      >
                        {run.error}
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td miw={140}>
                    <Text size="sm" className="tabular">
                      {run.generation} / {experiment.n_gen}
                    </Text>
                    <Progress size="xs" value={(100 * run.generation) / experiment.n_gen} />
                  </Table.Td>
                  <Table.Td className="tabular">
                    {seconds === null ? "—" : formatDuration(seconds)}
                  </Table.Td>
                  {INDICATORS.map((name) => (
                    <Table.Td key={name} ta="right" className="tabular">
                      {formatNumber(last(name))}
                    </Table.Td>
                  ))}
                  <Table.Td>
                    <Tooltip label="Download metrics (CSV)">
                      <ActionIcon
                        component="a"
                        href={`/api/runs/${run.id}/metrics.csv`}
                        variant="subtle"
                        color="gray"
                        aria-label={`Download metrics of run ${run.index + 1}`}
                      >
                        <IconDownload size={16} />
                      </ActionIcon>
                    </Tooltip>
                  </Table.Td>
                </Table.Tr>
              );
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Card>
  );
}
