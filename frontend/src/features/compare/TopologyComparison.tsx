import {
  Alert,
  Anchor,
  Button,
  Card,
  ColorSwatch,
  Group,
  Input,
  Loader,
  SegmentedControl,
  Select,
  Stack,
  Switch,
  Table,
  Text,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconInfoCircle } from "@tabler/icons-react";
import { useState } from "react";
import { Link } from "react-router";

import {
  useAnalysisGroups,
  useAnalysisGroupSummaries,
  useCreateAnalysisBatches,
} from "../../api/queries";
import type { AnalysisGroup } from "../../api/types";
import { PlotlyChart } from "../../components/PlotlyChart";
import { useChartTheme } from "../../hooks/useChartTheme";
import { ANALYSIS_KIND_LABELS, describeConfig } from "../../lib/analysisModel";
import { formatNumber } from "../../lib/format";
import { bandTraces, baseLayout } from "../../lib/plots";
import {
  DEFAULT_QUANTITY,
  QUANTITIES,
  commonDimensions,
  defaultGroupKeys,
  differingSettings,
  scaleOptions,
  tableValue,
  type AnalysisKind,
} from "../../lib/topologyCompare";
import { homologyLabel } from "../../lib/topologyPlots";
import type { ComparedExperiment } from "./ComparePage";

const KINDS = Object.keys(ANALYSIS_KIND_LABELS) as AnalysisKind[];

function groupLabel(group: AnalysisGroup): string {
  const computing = group.pending > 0 ? ` · ${group.pending} computing` : "";
  return `${describeConfig(group.config)} · ${group.runs} run(s)${computing}`;
}

/**
 * Median and interquartile range of a topological summary across each
 * experiment's runs, from analyses that share a configuration.
 */
export function TopologyComparison({ experiments }: { experiments: ComparedExperiment[] }) {
  const theme = useChartTheme();
  const groupQueries = useAnalysisGroups(experiments.map((e) => e.id));
  const groupsOf: Record<string, AnalysisGroup[]> = Object.fromEntries(
    experiments.map((e, i) => [e.id, groupQueries[i]?.data ?? []]),
  );
  const has = (k: AnalysisKind) =>
    Object.values(groupsOf).some((groups) => groups.some((g) => g.config.kind === k));

  const [pickedKind, setPickedKind] = useState<AnalysisKind | null>(null);
  const kind = pickedKind ?? (has("topology") || !has("zigzag") ? "topology" : "zigzag");
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [quantities, setQuantities] = useState(DEFAULT_QUANTITY);
  const [dimensionPick, setDimension] = useState(0);
  const [scalePick, setScale] = useState(0);
  const [logScale, setLogScale] = useState(false);
  const createBatches = useCreateAnalysisBatches();

  const defaults = defaultGroupKeys(groupsOf, kind);
  const rows = experiments.map((experiment) => {
    const groups = (groupsOf[experiment.id] ?? []).filter((g) => g.config.kind === kind);
    const key = picked[`${kind}:${experiment.id}`] ?? defaults[experiment.id];
    return { experiment, groups, group: groups.find((g) => g.key === key) ?? null };
  });
  const configs = rows.flatMap((r) => (r.group ? [r.group.config] : []));
  const dimensions = commonDimensions(configs);
  const dimension = dimensions.includes(dimensionPick) ? dimensionPick : 0;
  const scales = scaleOptions(configs);
  const epsilonIndex = kind === "zigzag" && scalePick < scales.length ? scalePick : 0;
  const quantity = quantities[kind];
  const meaning = QUANTITIES[kind][quantity];

  const requests = rows.flatMap((r) =>
    r.group && r.group.runs > 0
      ? [{ experimentId: r.experiment.id, group: r.group, dimension, epsilonIndex }]
      : [],
  );
  const summaries = useAnalysisGroupSummaries(requests);
  const summaryOf = new Map(requests.map((r, i) => [r.experimentId, summaries[i]]));

  const reference = rows.find((r) => r.group)?.group ?? null;
  const missing = rows.filter((r) => !r.group);
  const differing = differingSettings(configs, epsilonIndex, dimension);
  const select = (experimentId: string, key: string) =>
    setPicked((current) => ({ ...current, [`${kind}:${experimentId}`]: key }));

  /** Show the reference configuration everywhere, computing it where it is missing. */
  const alignOnReference = () => {
    if (!reference) return;
    const toCompute: ComparedExperiment[] = [];
    for (const row of rows) {
      if (row.group?.key === reference.key) continue;
      if (row.groups.some((g) => g.key === reference.key)) select(row.experiment.id, reference.key);
      else toCompute.push(row.experiment);
    }
    if (toCompute.length === 0) return;
    createBatches.mutate(
      { experimentIds: toCompute.map((e) => e.id), config: reference.config },
      {
        onSuccess: (outcomes) =>
          outcomes.forEach((outcome, i) => {
            const experiment = toCompute[i];
            if (!experiment) return;
            if (outcome.status === "fulfilled") select(experiment.id, reference.key);
            notifications.show(
              outcome.status === "fulfilled"
                ? { message: `Computing the analysis for ${experiment.name}` }
                : {
                    color: "red",
                    title: `Could not analyse ${experiment.name}`,
                    message: String((outcome.reason as Error).message ?? outcome.reason),
                  },
            );
          }),
      },
    );
  };

  const traces = rows.flatMap(({ experiment }) => {
    const series = summaryOf.get(experiment.id)?.data?.series[quantity];
    const summary = summaryOf.get(experiment.id)?.data;
    if (!series || !summary) return [];
    return bandTraces(
      { generation: summary.generation, n_runs: summary.n_runs, ...series },
      experiment.color,
      experiment.name,
    );
  });
  const axis = baseLayout(theme);
  const label = `${meaning?.label ?? quantity} (${homologyLabel(dimension)})`;
  const loading = groupQueries.some((q) => q.isPending);

  return (
    <Stack gap="md">
      <Group align="flex-end" wrap="wrap">
        <Input.Wrapper label="Tool">
          <SegmentedControl
            display="flex"
            value={kind}
            onChange={(value) => setPickedKind(value as AnalysisKind)}
            data={KINDS.map((k) => ({ value: k, label: ANALYSIS_KIND_LABELS[k] }))}
          />
        </Input.Wrapper>
        <Select
          label="Summary"
          w={300}
          allowDeselect={false}
          value={quantity}
          onChange={(value) => value && setQuantities((q) => ({ ...q, [kind]: value }))}
          data={Object.entries(QUANTITIES[kind]).map(([value, q]) => ({ value, label: q.label }))}
        />
        <Input.Wrapper label="Homology">
          <SegmentedControl
            display="flex"
            value={String(dimension)}
            onChange={(value) => setDimension(Number(value))}
            data={dimensions.map((k) => ({ value: String(k), label: homologyLabel(k) }))}
          />
        </Input.Wrapper>
        {kind === "zigzag" && scales.length > 0 && (
          <Input.Wrapper label="Scale">
            <SegmentedControl
              display="flex"
              value={String(epsilonIndex)}
              onChange={(value) => setScale(Number(value))}
              data={scales}
            />
          </Input.Wrapper>
        )}
        <Switch
          ml="auto"
          mb={8}
          label="Log scale"
          checked={logScale}
          onChange={(e) => setLogScale(e.currentTarget.checked)}
        />
      </Group>

      {loading ? (
        <Loader size="sm" />
      ) : !reference ? (
        <Alert icon={<IconInfoCircle size={16} />} color="gray">
          None of these experiments has a “{ANALYSIS_KIND_LABELS[kind]}” analysis yet. Compute one
          in an experiment’s Topology tab, over every run, and it can then be repeated here for the
          others.
        </Alert>
      ) : (
        (differing.length > 0 || missing.length > 0) && (
          <Alert
            icon={<IconAlertTriangle size={16} />}
            color="yellow"
            title={
              differing.length > 0
                ? `The analyses differ in ${differing.join(", ")}`
                : `${missing.length} experiment(s) have no analysis of this kind`
            }
          >
            <Stack gap="xs" align="flex-start">
              <Text size="sm">
                {differing.length > 0
                  ? "Topological summaries depend on the scale and on the space the distances are measured in: compare analyses with the same settings."
                  : "Their rows stay empty until the analysis is computed."}{" "}
                Applying the same configuration everywhere computes it over every finished run of
                the experiments that lack it.
              </Text>
              <Button
                size="xs"
                variant="light"
                loading={createBatches.isPending}
                onClick={alignOnReference}
              >
                Use “{describeConfig(reference.config)}” for every experiment
              </Button>
            </Stack>
          </Alert>
        )
      )}

      {reference && (
        <>
          <Card withBorder padding="xs">
            <PlotlyChart
              ariaLabel={`${label} per generation for the selected experiments`}
              height={480}
              data={traces}
              layout={baseLayout(theme, {
                xaxis: { ...axis.xaxis, title: { text: "Generation" } },
                yaxis: {
                  ...axis.yaxis,
                  title: { text: meaning?.event ? `${label} per generation` : label },
                  type: logScale ? "log" : "linear",
                },
                hovermode: "x",
              })}
            />
            <Text size="xs" c="dimmed" px="xs" pb={4}>
              Median across runs with the interquartile range.
              {meaning?.event &&
                " Events are counted per generation; the table compares each run's total."}
            </Text>
          </Card>
          <Card withBorder padding={0}>
            <Table.ScrollContainer minWidth={960}>
              <Table verticalSpacing="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Experiment</Table.Th>
                    <Table.Th>Analysis</Table.Th>
                    <Table.Th ta="right">Runs</Table.Th>
                    <Table.Th ta="right">
                      {meaning?.event ? "Median total per run" : "Final median"}
                    </Table.Th>
                    <Table.Th ta="right">IQR</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {rows.map(({ experiment, groups, group }) => {
                    const query = summaryOf.get(experiment.id);
                    const value = query?.data ? tableValue(query.data, quantity) : null;
                    return (
                      <Table.Tr key={experiment.id}>
                        <Table.Td>
                          <Group gap="xs" wrap="nowrap">
                            <ColorSwatch color={experiment.color} size={12} />
                            <Anchor component={Link} to={`/experiments/${experiment.id}`} size="sm">
                              {experiment.name}
                            </Anchor>
                          </Group>
                        </Table.Td>
                        <Table.Td>
                          {groups.length > 0 ? (
                            <Select
                              size="xs"
                              miw={440}
                              aria-label={`Analysis of ${experiment.name}`}
                              allowDeselect={false}
                              value={group?.key ?? null}
                              onChange={(key) => key && select(experiment.id, key)}
                              data={groups.map((g) => ({ value: g.key, label: groupLabel(g) }))}
                            />
                          ) : (
                            <Text size="sm" c="dimmed">
                              No analysis of this kind
                            </Text>
                          )}
                          {query?.error && (
                            <Text size="xs" c="red">
                              {query.error.message}
                            </Text>
                          )}
                        </Table.Td>
                        <Table.Td ta="right" className="tabular">
                          {group ? group.runs : "—"}
                        </Table.Td>
                        <Table.Td ta="right" className="tabular">
                          {value ? formatNumber(value.median) : "—"}
                        </Table.Td>
                        <Table.Td ta="right" className="tabular">
                          {value ? `[${formatNumber(value.q1)}, ${formatNumber(value.q3)}]` : "—"}
                        </Table.Td>
                      </Table.Tr>
                    );
                  })}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Card>
        </>
      )}
    </Stack>
  );
}
