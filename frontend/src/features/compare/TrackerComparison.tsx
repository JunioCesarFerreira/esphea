import {
  Alert,
  Anchor,
  Card,
  ColorSwatch,
  Group,
  Input,
  Loader,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { IconAlertTriangle, IconInfoCircle } from "@tabler/icons-react";
import { useState } from "react";
import { Link } from "react-router";

import { useAnalysisGroups, useTrackerGroupRuns } from "../../api/queries";
import type { AnalysisGroup, TrackerRuns } from "../../api/types";
import { PlotlyChart } from "../../components/PlotlyChart";
import { useChartTheme } from "../../hooks/useChartTheme";
import { describeConfig } from "../../lib/analysisModel";
import { formatNumber } from "../../lib/format";
import { defaultGroupKeys, differingSettings, scaleOptions } from "../../lib/topologyCompare";
import {
  a12,
  boxLayout,
  DEFAULT_LONG_LIFETIME,
  DESCRIPTIVE_FIELDS,
  direction,
  experimentBoxTraces,
  METHOD_LABELS,
  METHODS,
  quartiles,
  RUN_FIELDS,
  TRACKERS,
  type RunField,
} from "../../lib/trackerModel";
import type { ComparedExperiment } from "./ComparePage";

interface Row {
  experiment: ComparedExperiment;
  groups: AnalysisGroup[];
  group: AnalysisGroup | null;
  runs: TrackerRuns | undefined;
  error: Error | null;
}

/** A₁₂ of every method against the reference, flagged where a tracker leads elsewhere. */
function EffectCells({ row, reference, field }: { row: Row; reference: Row; field: RunField }) {
  const effect = (method: string) =>
    row.runs && reference.runs
      ? a12(row.runs.methods[method]?.[field] ?? [], reference.runs.methods[method]?.[field] ?? [])
      : null;
  const zigzag = direction(effect("zigzag"));
  return METHODS.map((method) => {
    const value = effect(method);
    const differs = method !== "zigzag" && zigzag !== null && direction(value) !== zigzag;
    return (
      <Table.Td key={method} ta="right">
        {value === null ? (
          "—"
        ) : (
          <Group gap={4} justify="flex-end" wrap="nowrap">
            {differs && (
              <IconAlertTriangle size={14} aria-label="direction differs from the zigzag" />
            )}
            <Text size="sm" fw={differs ? 600 : undefined} className="tabular">
              {value.toFixed(2)}
            </Text>
          </Group>
        )}
      </Table.Td>
    );
  });
}

function medianText(runs: TrackerRuns | undefined, method: string, field: RunField): string {
  const spread = quartiles(runs?.methods[method]?.[field] ?? []);
  return spread ? formatNumber(spread.median) : "—";
}

/**
 * The zigzag and the niche trackers across each experiment's runs: whether the
 * pairing rule changes how experiments compare.
 */
export function TrackerComparison({ experiments }: { experiments: ComparedExperiment[] }) {
  const theme = useChartTheme();
  const groupQueries = useAnalysisGroups(experiments.map((e) => e.id));
  const groupsOf: Record<string, AnalysisGroup[]> = Object.fromEntries(
    experiments.map((e, i) => [e.id, groupQueries[i]?.data ?? []]),
  );
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [scalePick, setScale] = useState(0);
  const [longLifetime, setLongLifetime] = useState(DEFAULT_LONG_LIFETIME);
  const [field, setField] = useState<RunField>("n_long");

  const defaults = defaultGroupKeys(groupsOf, "zigzag");
  const chosen = experiments.map((experiment) => {
    const groups = (groupsOf[experiment.id] ?? []).filter((g) => g.config.kind === "zigzag");
    const key = picked[experiment.id] ?? defaults[experiment.id];
    return { experiment, groups, group: groups.find((g) => g.key === key) ?? null };
  });
  const configs = chosen.flatMap((r) => (r.group ? [r.group.config] : []));
  const scales = scaleOptions(configs);
  const epsilonIndex = scalePick < scales.length ? scalePick : 0;
  const differing = differingSettings(configs, epsilonIndex);

  const requests = chosen.flatMap((r) =>
    r.group && r.group.runs > 0
      ? [{ experimentId: r.experiment.id, group: r.group, epsilonIndex, longLifetime }]
      : [],
  );
  const results = useTrackerGroupRuns(requests);
  const resultOf = new Map(requests.map((r, i) => [r.experimentId, results[i]]));
  const rows: Row[] = chosen.map((r) => ({
    ...r,
    runs: resultOf.get(r.experiment.id)?.data,
    error: resultOf.get(r.experiment.id)?.error ?? null,
  }));
  const withRuns = rows.filter((r) => r.runs);
  const reference = withRuns[0] ?? null;
  const loading = groupQueries.some((q) => q.isPending);

  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed" maw={900}>
        The niche trackers T1, T1o and T2 follow the same niches as the zigzag H₀ barcode but pair
        their births and deaths locally. If a tracker ranks two experiments differently from the
        zigzag, the conclusion depends on the pairing rule.
      </Text>
      <Group align="flex-end" wrap="wrap">
        <Select
          label="Summary"
          w={300}
          allowDeselect={false}
          value={field}
          onChange={(value) => value && setField(value as RunField)}
          data={DESCRIPTIVE_FIELDS.map((value) => ({ value, label: RUN_FIELDS[value].label }))}
        />
        {scales.length > 0 && (
          <Input.Wrapper label="Scale">
            <SegmentedControl
              display="flex"
              value={String(epsilonIndex)}
              onChange={(value) => setScale(Number(value))}
              data={scales}
            />
          </Input.Wrapper>
        )}
        <NumberInput
          w={170}
          label="Long bars (≥ steps)"
          min={1}
          value={longLifetime}
          onChange={(v) => typeof v === "number" && v >= 1 && setLongLifetime(v)}
        />
      </Group>

      {loading ? (
        <Loader size="sm" />
      ) : configs.length === 0 ? (
        <Alert icon={<IconInfoCircle size={16} />} color="gray">
          None of these experiments has a zigzag analysis yet. The niche trackers are computed with
          it: start one over every run in an experiment’s Topology tab, or align the experiments in
          the Topology tab of this page.
        </Alert>
      ) : (
        (differing.length > 0 || configs.length < experiments.length) && (
          <Alert icon={<IconAlertTriangle size={16} />} color="yellow">
            {differing.length > 0
              ? `The zigzag analyses differ in ${differing.join(", ")}: compare analyses with the same settings.`
              : "Some experiments have no zigzag analysis."}{" "}
            The Topology tab can compute the same configuration for every experiment.
          </Alert>
        )
      )}

      {reference && (
        <Card withBorder padding="xs">
          <PlotlyChart
            ariaLabel={`${RUN_FIELDS[field].label} per method for the selected experiments`}
            height={440}
            data={experimentBoxTraces(
              withRuns.flatMap((r) =>
                r.runs
                  ? [{ name: r.experiment.name, color: r.experiment.color, runs: r.runs }]
                  : [],
              ),
              field,
            )}
            layout={boxLayout(theme, field, true)}
          />
          <Text size="xs" c="dimmed" px="xs" pb={4}>
            Each point is a run. Long bars live at least {longLifetime} steps ({longLifetime / 2}{" "}
            generations).
          </Text>
        </Card>
      )}

      {configs.length > 0 && (
        <Card withBorder padding={0}>
          <Table.ScrollContainer minWidth={1080}>
            <Table verticalSpacing="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th rowSpan={2}>Experiment</Table.Th>
                  <Table.Th rowSpan={2}>Analysis</Table.Th>
                  <Table.Th rowSpan={2} ta="right">
                    Runs
                  </Table.Th>
                  <Table.Th colSpan={METHODS.length} ta="center">
                    Median
                  </Table.Th>
                  <Table.Th colSpan={METHODS.length} ta="center">
                    A₁₂ against {reference?.experiment.name ?? "the first experiment"}
                  </Table.Th>
                </Table.Tr>
                <Table.Tr>
                  {[...METHODS, ...METHODS].map((method, i) => (
                    <Table.Th key={`${method}-${i}`} ta="right">
                      {METHOD_LABELS[method]}
                    </Table.Th>
                  ))}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {rows.map((row) => (
                  <Table.Tr key={row.experiment.id}>
                    <Table.Td>
                      <Group gap="xs" wrap="nowrap">
                        <ColorSwatch color={row.experiment.color} size={12} />
                        <Anchor component={Link} to={`/experiments/${row.experiment.id}`} size="sm">
                          {row.experiment.name}
                        </Anchor>
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      {row.groups.length > 0 ? (
                        <Select
                          size="xs"
                          miw={300}
                          aria-label={`Zigzag analysis of ${row.experiment.name}`}
                          allowDeselect={false}
                          value={row.group?.key ?? null}
                          onChange={(key) =>
                            key &&
                            setPicked((current) => ({ ...current, [row.experiment.id]: key }))
                          }
                          data={row.groups.map((g) => ({
                            value: g.key,
                            label: `${describeConfig(g.config)} · ${g.runs} run(s)`,
                          }))}
                        />
                      ) : (
                        <Text size="sm" c="dimmed">
                          No zigzag analysis
                        </Text>
                      )}
                      {row.error && (
                        <Text size="xs" c="red">
                          {row.error.message}
                        </Text>
                      )}
                      {row.runs && row.runs.skipped > 0 && (
                        <Text size="xs" c="dimmed">
                          {row.runs.skipped} run(s) predate the niche trackers
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td ta="right" className="tabular">
                      {row.runs?.n_runs ?? "—"}
                    </Table.Td>
                    {METHODS.map((method) => (
                      <Table.Td key={method} ta="right" className="tabular">
                        {medianText(row.runs, method, field)}
                      </Table.Td>
                    ))}
                    {reference && row !== reference ? (
                      <EffectCells row={row} reference={reference} field={field} />
                    ) : (
                      <Table.Td colSpan={METHODS.length} ta="center" c="dimmed">
                        {row === reference ? "reference" : "—"}
                      </Table.Td>
                    )}
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          <Text size="xs" c="dimmed" px="sm" pb="xs">
            A₁₂ (Vargha–Delaney): probability that a run of the experiment has a larger value than a
            run of the reference; 0.5 is no difference, ≥ 0.56 or ≤ 0.44 at least a small effect.
            Marked: a tracker ({TRACKERS.map((t) => METHOD_LABELS[t]).join(", ")}) whose direction
            differs from the zigzag’s. Effect sizes only; no significance test is applied.
          </Text>
        </Card>
      )}
    </Stack>
  );
}
