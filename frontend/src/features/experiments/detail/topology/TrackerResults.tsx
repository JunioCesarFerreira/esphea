import { Alert, Group, NumberInput, Select, Stack, Table, Text } from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";
import { useState } from "react";

import { useTrackerBars, useTrackerBatchRuns, useTrackerComparison } from "../../../../api/queries";
import type { Analysis, MethodSummary, TrackerRuns } from "../../../../api/types";
import { PlotlyChart } from "../../../../components/PlotlyChart";
import { useChartTheme } from "../../../../hooks/useChartTheme";
import { formatInteger, formatNumber } from "../../../../lib/format";
import {
  atLeastLayout,
  atLeastTraces,
  boxLayout,
  DEFAULT_LONG_LIFETIME,
  formatShare,
  METHOD_DESCRIPTIONS,
  METHOD_LABELS,
  METHODS,
  methodBoxTraces,
  quartiles,
  RUN_FIELDS,
  trackerBarcodeTraces,
  trackerRows,
  type Method,
  type Resolution,
  type RunField,
  type Tracker,
} from "../../../../lib/trackerModel";
import { zigzagBarcodeLayout } from "../../../../lib/zigzagPlots";
import { Section } from "./Section";

const COMPARISON_NOTE =
  "Every method sees the same niches (ε-connected components) at each Pₜ, and the zigzag, T1 and T1o the same ones at each Rₜ: they differ only in how they link them over time.";

function Unavailable({ message }: { message: string }) {
  return (
    <Alert icon={<IconInfoCircle size={16} />} color="gray" title="Niche trackers unavailable">
      {message}
    </Alert>
  );
}

function LongLifetimeInput({
  value,
  onChange,
  max,
}: {
  value: number;
  onChange: (value: number) => void;
  max?: number;
}) {
  return (
    <NumberInput
      size="xs"
      w={160}
      label="Long bars (≥ steps)"
      min={1}
      max={max}
      value={value}
      onChange={(v) => typeof v === "number" && v >= 1 && onChange(v)}
    />
  );
}

/** Barcode of one tracker, shown in place of the zigzag barcode. */
export function TrackerBarcode({
  analysis,
  epsilonIndex,
  method,
  minLifetime,
  resolution,
}: {
  analysis: Analysis;
  epsilonIndex: number;
  method: Tracker;
  minLifetime: number;
  resolution: Resolution;
}) {
  const theme = useChartTheme();
  const bars = useTrackerBars(analysis.id, method, epsilonIndex, minLifetime);
  if (bars.error) return <Unavailable message={bars.error.message} />;
  if (!bars.data) return null;
  const rows = trackerRows(bars.data, resolution);
  const differing = rows.filter((row) => !row.matched).length;
  return (
    <>
      <Text size="xs" c="dimmed" mb={4}>
        {formatInteger(rows.length)} bars shown · {formatInteger(differing)} not in the zigzag (
        {resolution === "step" ? "same birth and death steps" : "same generations"})
      </Text>
      <PlotlyChart
        ariaLabel={`${METHOD_LABELS[method]} tracker barcode`}
        height={Math.min(900, Math.max(320, 120 + rows.length * 3))}
        data={trackerBarcodeTraces(bars.data, resolution, theme)}
        layout={zigzagBarcodeLayout(theme, bars.data.n_generations)}
      />
      <Text size="xs" c="dimmed" mt={4}>
        {METHOD_DESCRIPTIONS[method]}
      </Text>
    </>
  );
}

function ComparisonTable({ methods }: { methods: MethodSummary[] }) {
  return (
    <Table.ScrollContainer minWidth={860}>
      <Table verticalSpacing={6} fz="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th rowSpan={2}>Method</Table.Th>
            <Table.Th rowSpan={2} ta="right">
              Bars
            </Table.Th>
            <Table.Th rowSpan={2} ta="right">
              Long bars
            </Table.Th>
            <Table.Th colSpan={2} ta="center">
              Lifetime (steps)
            </Table.Th>
            <Table.Th colSpan={2} ta="center">
              Zigzag bars reproduced
            </Table.Th>
            <Table.Th colSpan={2} ta="center">
              Long zigzag bars reproduced
            </Table.Th>
          </Table.Tr>
          <Table.Tr>
            <Table.Th ta="right">median</Table.Th>
            <Table.Th ta="right">90th pct.</Table.Th>
            <Table.Th ta="right">same steps</Table.Th>
            <Table.Th ta="right">same gen.</Table.Th>
            <Table.Th ta="right">same steps</Table.Th>
            <Table.Th ta="right">same gen.</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody className="tabular">
          {methods.map((m) => (
            <Table.Tr key={m.method}>
              <Table.Td>{METHOD_LABELS[m.method as Method] ?? m.method}</Table.Td>
              <Table.Td ta="right">{formatInteger(m.n_bars)}</Table.Td>
              <Table.Td ta="right">{formatInteger(m.n_long)}</Table.Td>
              <Table.Td ta="right">{formatNumber(m.median_lifetime)}</Table.Td>
              <Table.Td ta="right">{formatNumber(m.p90_lifetime)}</Table.Td>
              {m.method === "zigzag" ? (
                <Table.Td colSpan={4} ta="center" c="dimmed">
                  reference
                </Table.Td>
              ) : (
                <>
                  <Table.Td ta="right">{formatShare(m.agreement_step)}</Table.Td>
                  <Table.Td ta="right">{formatShare(m.agreement_generation)}</Table.Td>
                  <Table.Td ta="right">{formatShare(m.long_agreement_step)}</Table.Td>
                  <Table.Td ta="right">{formatShare(m.long_agreement_generation)}</Table.Td>
                </>
              )}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

/** The zigzag and the three trackers of one run, side by side. */
export function TrackerRunComparison({
  analysis,
  epsilonIndex,
  nSteps,
}: {
  analysis: Analysis;
  epsilonIndex: number;
  nSteps: number;
}) {
  const theme = useChartTheme();
  const [longLifetime, setLongLifetime] = useState(Math.min(DEFAULT_LONG_LIFETIME, nSteps));
  const comparison = useTrackerComparison(analysis.id, epsilonIndex, longLifetime);
  return (
    <Section
      title="Zigzag and niche trackers · H₀"
      description={`${COMPARISON_NOTE} Reproduced: share of the zigzag bars a tracker also has, with the same birth and death steps or in the same generations.`}
      controls={<LongLifetimeInput value={longLifetime} onChange={setLongLifetime} max={nSteps} />}
    >
      {comparison.error ? (
        <Unavailable message={comparison.error.message} />
      ) : (
        comparison.data && (
          <Stack gap="sm">
            <ComparisonTable methods={comparison.data.methods} />
            <PlotlyChart
              ariaLabel="Bars alive at least L steps, per method"
              height={340}
              data={atLeastTraces(comparison.data.methods, theme)}
              layout={atLeastLayout(theme)}
            />
            <Text size="xs" c="dimmed">
              Long bars live at least {longLifetime} steps ({longLifetime / 2} generations); bars
              alive at the end count as long. Lifetime quantiles use the bars that end before the
              last step.
            </Text>
          </Stack>
        )
      )}
    </Section>
  );
}

const BATCH_COLUMNS: readonly RunField[] = [
  "n_bars",
  "n_long",
  "median_lifetime",
  "agreement_step",
  "agreement_generation",
  "long_agreement_step",
  "long_agreement_generation",
];

function spreadText(values: (number | null)[] | undefined, share: boolean): string {
  const spread = quartiles(values ?? []);
  if (!spread) return "—";
  const format = share ? formatShare : (v: number) => formatNumber(v);
  return `${format(spread.median)} [${format(spread.q1)}, ${format(spread.q3)}]`;
}

function BatchTable({ runs }: { runs: TrackerRuns }) {
  const cell = (method: Method, field: RunField) =>
    method === "zigzag" && RUN_FIELDS[field].share
      ? "—"
      : spreadText(runs.methods[method]?.[field], RUN_FIELDS[field].share);
  return (
    <Table.ScrollContainer minWidth={1080}>
      <Table verticalSpacing={6} fz="sm" style={{ whiteSpace: "nowrap" }}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th rowSpan={2}>Method</Table.Th>
            <Table.Th rowSpan={2} ta="right">
              Bars
            </Table.Th>
            <Table.Th rowSpan={2} ta="right">
              Long bars
            </Table.Th>
            <Table.Th rowSpan={2} ta="right">
              Median lifetime
            </Table.Th>
            <Table.Th colSpan={2} ta="center">
              Zigzag bars reproduced
            </Table.Th>
            <Table.Th colSpan={2} ta="center">
              Long zigzag bars reproduced
            </Table.Th>
          </Table.Tr>
          <Table.Tr>
            <Table.Th ta="right">same steps</Table.Th>
            <Table.Th ta="right">same gen.</Table.Th>
            <Table.Th ta="right">same steps</Table.Th>
            <Table.Th ta="right">same gen.</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody className="tabular">
          {METHODS.map((method) => (
            <Table.Tr key={method}>
              <Table.Td>{METHOD_LABELS[method]}</Table.Td>
              {BATCH_COLUMNS.map((field) => (
                <Table.Td key={field} ta="right">
                  {cell(method, field)}
                </Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

/** The zigzag and the trackers across the runs of a batch. */
export function TrackerBatchComparison({
  batchId,
  epsilonIndex,
}: {
  batchId: string;
  epsilonIndex: number;
}) {
  const theme = useChartTheme();
  const [longLifetime, setLongLifetime] = useState(DEFAULT_LONG_LIFETIME);
  const [field, setField] = useState<RunField>("n_long");
  const runs = useTrackerBatchRuns(batchId, epsilonIndex, longLifetime, true);
  return (
    <Section
      title="Zigzag and niche trackers across runs · H₀"
      description={`${COMPARISON_NOTE} Median [interquartile range] over the runs; each point of the chart is a run.`}
      controls={
        <Group gap="xs" align="flex-end">
          <Select
            size="xs"
            w={300}
            label="Chart"
            allowDeselect={false}
            value={field}
            onChange={(v) => v && setField(v as RunField)}
            data={Object.entries(RUN_FIELDS).map(([value, { label }]) => ({ value, label }))}
          />
          <LongLifetimeInput value={longLifetime} onChange={setLongLifetime} />
        </Group>
      }
    >
      {runs.error ? (
        <Unavailable message={runs.error.message} />
      ) : (
        runs.data && (
          <Stack gap="sm">
            {runs.data.skipped > 0 && (
              <Text size="xs" c="dimmed">
                {runs.data.skipped} run(s) left out: their analysis predates the niche trackers.
              </Text>
            )}
            <BatchTable runs={runs.data} />
            <PlotlyChart
              ariaLabel={`${RUN_FIELDS[field].label} per method across runs`}
              height={360}
              data={methodBoxTraces(runs.data, field, theme)}
              layout={{ ...boxLayout(theme, field, false), showlegend: false }}
            />
          </Stack>
        )
      )}
    </Section>
  );
}
