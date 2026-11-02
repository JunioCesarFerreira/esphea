import {
  Card,
  Chip,
  Group,
  SegmentedControl,
  Select,
  SimpleGrid,
  Slider,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useMemo, useState, type ReactNode } from "react";

import {
  useBettiCurves,
  useDiagram,
  useDistanceMatrix,
  useTopologySeries,
} from "../../../../api/queries";
import type { Analysis } from "../../../../api/types";
import { PlotlyChart } from "../../../../components/PlotlyChart";
import { QueryState } from "../../../../components/QueryState";
import { useChartTheme } from "../../../../hooks/useChartTheme";
import {
  barcodeLayout,
  barcodeTraces,
  bettiHeatmap,
  displayScale,
  distanceTraces,
  generationLayout,
  homologyLabel,
  matrixHeatmap,
  METRIC_LABELS,
  persistenceDiagramLayout,
  persistenceDiagramTraces,
  type Reference,
  SUMMARY_LABELS,
  type Summary,
  summaryTraces,
} from "../../../../lib/topologyPlots";

function ChartCard({
  title,
  description,
  controls,
  children,
}: {
  title: string;
  description: string;
  controls?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card withBorder padding="md">
      <Group justify="space-between" align="flex-start" mb="xs" wrap="wrap">
        <div>
          <Title order={5}>{title}</Title>
          <Text size="xs" c="dimmed" maw={560}>
            {description}
          </Text>
        </div>
        <Group gap="xs">{controls}</Group>
      </Group>
      {children}
    </Card>
  );
}

function DimensionPicker({
  max,
  value,
  onChange,
}: {
  max: number;
  value: number;
  onChange: (d: number) => void;
}) {
  if (max === 0) return null;
  return (
    <SegmentedControl
      size="xs"
      value={String(value)}
      onChange={(v) => onChange(Number(v))}
      data={Array.from({ length: max + 1 }, (_, k) => ({
        value: String(k),
        label: homologyLabel(k),
      }))}
    />
  );
}

export function AnalysisResults({ analysis }: { analysis: Analysis }) {
  const theme = useChartTheme();
  const maxDimension = analysis.config.max_dimension;
  const series = useTopologySeries(analysis.id);
  const generations = useMemo(() => series.data?.generation ?? [], [series.data]);
  const [position, setPosition] = useState<number | null>(null);
  const index = position ?? generations.length - 1;
  const generation = generations[index] ?? null;
  const diagram = useDiagram(analysis.id, generation);

  const [view, setView] = useState("barcode");
  const [shown, setShown] = useState<string[]>(
    Array.from({ length: maxDimension + 1 }, (_, k) => String(k)),
  );
  const dimensions = useMemo(() => new Set(shown.map(Number)), [shown]);

  const [distanceDimension, setDistanceDimension] = useState(0);
  const [metric, setMetric] = useState("bottleneck");
  const [reference, setReference] = useState<Reference>("previous");
  const [bettiDimension, setBettiDimension] = useState(0);
  const betti = useBettiCurves(analysis.id, bettiDimension);
  const [summary, setSummary] = useState<Summary>("total_persistence");
  const [matrixDimension, setMatrixDimension] = useState(0);
  const [matrixMetric, setMatrixMetric] = useState("bottleneck");
  const matrix = useDistanceMatrix(
    analysis.id,
    matrixDimension,
    matrixMetric,
    analysis.config.distance_matrix,
  );

  const metricOptions = Object.entries(METRIC_LABELS).map(([value, label]) => ({ value, label }));
  const epsilon = analysis.config.max_epsilon;
  const edge = displayScale(series.data?.max_finite_death ?? 0, epsilon);

  return (
    <QueryState isPending={series.isPending} error={series.error}>
      {series.data && (
        <Stack gap="md">
          <ChartCard
            title="Barcodes"
            description="Vietoris–Rips persistence of the selected generation. The scale is shown up to the largest finite death of the analysis; features still alive at ε max end in an arrow (triangles in the diagram) at that edge."
            controls={
              <>
                <Chip.Group multiple value={shown} onChange={setShown}>
                  <Group gap={4}>
                    {Array.from({ length: maxDimension + 1 }, (_, k) => (
                      <Chip key={k} value={String(k)} size="xs" variant="outline">
                        {homologyLabel(k)}
                      </Chip>
                    ))}
                  </Group>
                </Chip.Group>
                <SegmentedControl
                  size="xs"
                  value={view}
                  onChange={setView}
                  data={[
                    { value: "barcode", label: "Barcode" },
                    { value: "diagram", label: "Diagram" },
                  ]}
                />
              </>
            }
          >
            <Group gap="md" wrap="nowrap" mb="xs">
              <Slider
                style={{ flex: 1 }}
                min={0}
                max={Math.max(generations.length - 1, 0)}
                value={Math.max(index, 0)}
                label={(i) => `generation ${generations[i] ?? 0}`}
                onChange={setPosition}
              />
              <Text size="sm" w={130} ta="right" className="tabular">
                Generation {generation ?? "—"}
              </Text>
            </Group>
            {diagram.data && (
              <PlotlyChart
                ariaLabel={`Persistence ${view} of generation ${generation}`}
                height={view === "barcode" ? 460 : 480}
                data={
                  view === "barcode"
                    ? barcodeTraces(diagram.data, dimensions, theme, edge)
                    : persistenceDiagramTraces(diagram.data, dimensions, theme, edge)
                }
                layout={
                  view === "barcode"
                    ? barcodeLayout(theme, edge)
                    : persistenceDiagramLayout(theme, edge)
                }
              />
            )}
          </ChartCard>

          <ChartCard
            title="Distance between barcodes"
            description={
              metric === "bottleneck"
                ? "Bottleneck distance per generation, with twice the Hausdorff distance between the point clouds: the stability theorem guarantees it is an upper bound."
                : "1-Wasserstein distance per generation: sums every change of the diagram, not only the largest."
            }
            controls={
              <>
                <DimensionPicker
                  max={maxDimension}
                  value={distanceDimension}
                  onChange={setDistanceDimension}
                />
                <SegmentedControl
                  size="xs"
                  value={metric}
                  onChange={setMetric}
                  data={metricOptions}
                />
                <SegmentedControl
                  size="xs"
                  value={reference}
                  onChange={(v) => setReference(v as Reference)}
                  data={[
                    { value: "previous", label: "To previous" },
                    { value: "final", label: "To final" },
                  ]}
                />
              </>
            }
          >
            <PlotlyChart
              ariaLabel="Distance between barcodes per generation"
              height={360}
              data={distanceTraces(series.data, distanceDimension, metric, reference, theme)}
              layout={generationLayout(
                theme,
                `${METRIC_LABELS[metric]} (${homologyLabel(distanceDimension)})`,
              )}
            />
          </ChartCard>

          <SimpleGrid cols={{ base: 1, lg: 2 }}>
            <ChartCard
              title="Betti curves"
              description="Number of features alive at each scale ε, for every generation."
              controls={
                <DimensionPicker
                  max={maxDimension}
                  value={bettiDimension}
                  onChange={setBettiDimension}
                />
              }
            >
              {betti.data && (
                <PlotlyChart
                  ariaLabel={`Betti curves of ${homologyLabel(bettiDimension)}`}
                  height={360}
                  data={bettiHeatmap(betti.data, theme)}
                  layout={generationLayout(theme, "ε", {
                    hovermode: "closest",
                    yaxis: { ...generationLayout(theme, "ε").yaxis, range: [0, edge] },
                  })}
                />
              )}
            </ChartCard>
            <ChartCard
              title="Summaries"
              description="Scalar summaries of each generation's diagram."
              controls={
                <Select
                  size="xs"
                  w={190}
                  value={summary}
                  allowDeselect={false}
                  onChange={(v) => v && setSummary(v as Summary)}
                  data={Object.entries(SUMMARY_LABELS).map(([value, label]) => ({ value, label }))}
                />
              }
            >
              <PlotlyChart
                ariaLabel={SUMMARY_LABELS[summary]}
                height={360}
                data={summaryTraces(series.data, summary, theme)}
                layout={generationLayout(theme, SUMMARY_LABELS[summary])}
              />
            </ChartCard>
          </SimpleGrid>

          {analysis.config.distance_matrix && (
            <ChartCard
              title="Distance matrix"
              description="Distance between the barcodes of every pair of (up to 100) generations."
              controls={
                <>
                  <DimensionPicker
                    max={maxDimension}
                    value={matrixDimension}
                    onChange={setMatrixDimension}
                  />
                  <SegmentedControl
                    size="xs"
                    value={matrixMetric}
                    onChange={setMatrixMetric}
                    data={metricOptions}
                  />
                </>
              }
            >
              {matrix.data && (
                <PlotlyChart
                  ariaLabel="Pairwise distance matrix between generations"
                  height={520}
                  data={matrixHeatmap(matrix.data, theme)}
                  layout={generationLayout(theme, "Generation", {
                    hovermode: "closest",
                    yaxis: {
                      ...generationLayout(theme, "Generation").yaxis,
                      scaleanchor: "x",
                      constrain: "domain",
                    },
                    xaxis: { ...generationLayout(theme, "Generation").xaxis, constrain: "domain" },
                  })}
                />
              )}
            </ChartCard>
          )}
        </Stack>
      )}
    </QueryState>
  );
}
