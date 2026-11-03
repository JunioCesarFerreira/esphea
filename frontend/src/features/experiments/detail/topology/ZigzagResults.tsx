import {
  Alert,
  Card,
  Group,
  NumberInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Slider,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";
import { useMemo, useState, type ReactNode } from "react";

import {
  useZigzagBars,
  useZigzagBatchSummary,
  useZigzagEvents,
  useZigzagRepresentative,
} from "../../../../api/queries";
import type { Analysis, ZigzagAnalysisConfig } from "../../../../api/types";
import { PlotlyChart } from "../../../../components/PlotlyChart";
import { useChartTheme } from "../../../../hooks/useChartTheme";
import { formatInteger, formatNumber } from "../../../../lib/format";
import { baseLayout, objectiveSpaceLayout } from "../../../../lib/plots";
import { homologyLabel } from "../../../../lib/topologyPlots";
import {
  barRows,
  BATCH_VIEWS,
  batchTraces,
  type BatchView,
  lifetimeHistogramTraces,
  MAX_BARS_WITH_MARKERS,
  representativeTraces,
  stepLabel,
  zigzagBarcodeLayout,
  zigzagBarcodeTraces,
  zigzagBettiTraces,
  zigzagEventTraces,
} from "../../../../lib/zigzagPlots";

function Section({
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
          <Text size="xs" c="dimmed" maw={620}>
            {description}
          </Text>
        </div>
        <Group gap="xs">{controls}</Group>
      </Group>
      {children}
    </Card>
  );
}

function RepresentativeViewer({
  analysis,
  epsilonIndex,
  bar,
  birth,
  death,
  nObj,
}: {
  analysis: Analysis;
  epsilonIndex: number;
  bar: number;
  birth: number;
  death: number;
  nObj: number;
}) {
  const theme = useChartTheme();
  const [step, setStep] = useState(birth);
  const clamped = Math.min(Math.max(step, birth), death - 1);
  const view = useZigzagRepresentative(analysis.id, epsilonIndex, bar, clamped);
  const traces = view.data ? representativeTraces(view.data, theme) : null;
  return (
    <Stack gap="xs">
      <Group gap="md" wrap="nowrap">
        <Slider
          style={{ flex: 1 }}
          min={birth}
          max={Math.max(death - 1, birth)}
          value={clamped}
          label={stepLabel}
          onChange={setStep}
          disabled={death - 1 <= birth}
        />
        <Text size="sm" w={210} ta="right" className="tabular">
          {stepLabel(clamped)} · generation {Math.ceil(clamped / 2)}
          {clamped % 2 === 1 ? " (with offspring)" : ""}
        </Text>
      </Group>
      {nObj > 3 ? (
        <Alert icon={<IconInfoCircle size={16} />} color="gray">
          The representative can be drawn for two or three objectives.{" "}
          {view.data &&
            `${formatInteger(view.data.component.length || new Set((view.data.simplices ?? []).flat()).size)} individuals are involved at this step.`}
        </Alert>
      ) : (
        view.data && (
          <>
            {view.data.simplices === null && (
              <Text size="xs" c="dimmed">
                No representative is available at this step (a known limitation of the zigzag
                representatives for intervals open at birth and closed at death).
              </Text>
            )}
            <PlotlyChart
              ariaLabel={`Representative of bar ${bar} at ${stepLabel(clamped)}`}
              height={nObj === 3 ? 520 : 460}
              data={traces ?? []}
              layout={objectiveSpaceLayout(
                theme,
                nObj,
                `rep-${analysis.id}-${epsilonIndex}`,
                traces ?? [],
              )}
            />
          </>
        )
      )}
    </Stack>
  );
}

export function ZigzagResults({
  analysis,
  config,
  nObj,
}: {
  analysis: Analysis;
  config: ZigzagAnalysisConfig;
  nObj: number;
}) {
  const theme = useChartTheme();
  const epsilons = config.epsilons;
  const maxDimension = config.max_dimension ?? 0;
  const [epsilonIndex, setEpsilonIndex] = useState(0);
  const [dimension, setDimension] = useState(0);
  const [minLifetime, setMinLifetime] = useState(3);
  const [selected, setSelected] = useState<number | null>(null);
  const [scope, setScope] = useState<"run" | "batch">("run");
  const [batchView, setBatchView] = useState<BatchView>("births");

  const bars = useZigzagBars(analysis.id, epsilonIndex, dimension, minLifetime);
  const events = useZigzagEvents(analysis.id, epsilonIndex, dimension);
  const summary = useZigzagBatchSummary(
    analysis.batch_id ?? null,
    epsilonIndex,
    dimension,
    scope === "batch",
  );

  const rows = useMemo(() => (bars.data ? barRows(bars.data) : []), [bars.data]);
  const withRepresentative = rows
    .filter((row) => bars.data?.representative[bars.data.bar.indexOf(row.bar)] !== null)
    .sort((a, b) => b.death - b.birth - (a.death - a.birth));
  const chosen = rows.find((row) => row.bar === selected) ?? null;

  const controls = (
    <Group gap="xs" wrap="wrap">
      {epsilons.length > 1 && (
        <SegmentedControl
          size="xs"
          value={String(epsilonIndex)}
          onChange={(v) => {
            setEpsilonIndex(Number(v));
            setSelected(null);
          }}
          data={epsilons.map((e, i) => ({ value: String(i), label: `ε ${formatNumber(e)}` }))}
        />
      )}
      {maxDimension > 0 && (
        <SegmentedControl
          size="xs"
          value={String(dimension)}
          onChange={(v) => {
            setDimension(Number(v));
            setSelected(null);
          }}
          data={Array.from({ length: maxDimension + 1 }, (_, k) => ({
            value: String(k),
            label: homologyLabel(k),
          }))}
        />
      )}
      {analysis.batch_id && (
        <SegmentedControl
          size="xs"
          value={scope}
          onChange={(v) => setScope(v as "run" | "batch")}
          data={[
            { value: "run", label: "This run" },
            { value: "batch", label: "All runs" },
          ]}
        />
      )}
    </Group>
  );

  if (scope === "batch") {
    return (
      <Stack gap="md">
        {controls}
        <Section
          title="Across runs"
          description={`Median and interquartile range over the ${summary.data?.n_runs ?? "…"} runs of the batch, per generation.`}
          controls={
            <SegmentedControl
              size="xs"
              value={batchView}
              onChange={(v) => setBatchView(v as BatchView)}
              data={Object.entries(BATCH_VIEWS).map(([value, { label }]) => ({ value, label }))}
            />
          }
        >
          {summary.data && (
            <PlotlyChart
              ariaLabel="Zigzag summary across runs"
              height={420}
              data={batchTraces(summary.data, batchView, theme)}
              layout={baseLayout(theme, {
                hovermode: "x",
                xaxis: { ...baseLayout(theme).xaxis, title: { text: "Generation" } },
                yaxis: {
                  ...baseLayout(theme).yaxis,
                  title: { text: BATCH_VIEWS[batchView].label },
                },
              })}
            />
          )}
        </Section>
      </Stack>
    );
  }

  return (
    <Stack gap="md">
      {controls}
      {bars.data?.representatives_skipped && (
        <Alert icon={<IconInfoCircle size={16} />} color="yellow">
          Representatives were not extracted at this scale: {bars.data.representatives_skipped}.
        </Alert>
      )}
      <Section
        title={`Zigzag barcode · ${homologyLabel(dimension)} · ε ${formatNumber(epsilons[epsilonIndex])}`}
        description="Each bar is a feature followed across generations. Colour: what created it; end marker: what ended it (circle: offspring, cross: selection, arrow: still alive). Click a bar to inspect it."
        controls={
          <NumberInput
            size="xs"
            w={150}
            label="Min. lifetime (steps)"
            min={1}
            value={minLifetime}
            onChange={(v) => typeof v === "number" && v >= 1 && setMinLifetime(v)}
          />
        }
      >
        {bars.data && (
          <>
            <Text size="xs" c="dimmed" mb={4}>
              {formatInteger(bars.data.bar.length)} bars shown
              {bars.data.n_simplices ? ` · ${formatInteger(bars.data.n_simplices)} simplices` : ""}
              {bars.data.bar.length > MAX_BARS_WITH_MARKERS &&
                " · end markers hidden: raise the minimum lifetime to see how bars end"}
            </Text>
            <PlotlyChart
              ariaLabel="Zigzag barcode"
              height={Math.min(900, Math.max(320, 120 + rows.length * 3))}
              data={zigzagBarcodeTraces(bars.data, theme, selected)}
              layout={zigzagBarcodeLayout(theme, bars.data.n_generations)}
              onPointClick={(value) => typeof value === "number" && setSelected(value)}
            />
          </>
        )}
      </Section>

      <Section
        title="Representative"
        description="Where a feature lives in objective space: its niche (H₀, the ε-connected individuals) or its cycle (H₁/H₂), at any step of its life."
        controls={
          <Select
            size="xs"
            w={300}
            placeholder="Choose a long-lived feature"
            value={selected === null ? null : String(selected)}
            onChange={(v) => setSelected(v === null ? null : Number(v))}
            data={withRepresentative.slice(0, 50).map((row) => ({
              value: String(row.bar),
              label: `bar ${row.bar} · ${stepLabel(row.birth)} → ${row.death >= (bars.data?.n_steps ?? 0) ? "end" : stepLabel(row.death - 1)} · ${row.death - row.birth} steps`,
            }))}
          />
        }
      >
        {chosen ? (
          <RepresentativeViewer
            key={`${epsilonIndex}-${chosen.bar}`}
            analysis={analysis}
            epsilonIndex={epsilonIndex}
            bar={chosen.bar}
            birth={chosen.birth}
            death={chosen.death}
            nObj={nObj}
          />
        ) : (
          <Text size="sm" c="dimmed">
            Select a feature in the list or click a bar of the barcode.
          </Text>
        )}
      </Section>

      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Section
          title="Births and deaths per generation"
          description="Up: features created; down: features ended. Variation acts when offspring join (Pₜ₋₁ → Rₜ), selection when individuals are removed (Rₜ ← Pₜ)."
        >
          {events.data && (
            <PlotlyChart
              ariaLabel="Zigzag events by cause"
              height={380}
              data={zigzagEventTraces(events.data, theme)}
              layout={baseLayout(theme, {
                barmode: "relative",
                bargap: 0.15,
                hovermode: "x",
                xaxis: { ...baseLayout(theme).xaxis, title: { text: "Generation" } },
                yaxis: { ...baseLayout(theme).yaxis, title: { text: "features" } },
              })}
            />
          )}
        </Section>
        <Section
          title="Betti numbers"
          description="Number of features present in the population after selection (Pₜ) and with its offspring (Rₜ)."
        >
          {events.data && (
            <PlotlyChart
              ariaLabel="Zigzag Betti numbers"
              height={380}
              data={zigzagBettiTraces(events.data, theme)}
              layout={baseLayout(theme, {
                hovermode: "x",
                xaxis: { ...baseLayout(theme).xaxis, title: { text: "Generation" } },
                yaxis: { ...baseLayout(theme).yaxis, title: { text: `β${dimension}` } },
              })}
            />
          )}
        </Section>
      </SimpleGrid>

      <Section
        title="Lifetimes"
        description="How many steps the shown features survive, by what created them."
      >
        {bars.data && (
          <PlotlyChart
            ariaLabel="Distribution of zigzag lifetimes"
            height={320}
            data={lifetimeHistogramTraces(bars.data, theme)}
            layout={baseLayout(theme, {
              barmode: "stack",
              xaxis: { ...baseLayout(theme).xaxis, title: { text: "lifetime (steps)" } },
              yaxis: {
                ...baseLayout(theme).yaxis,
                title: { text: "features" },
                type: "log",
                dtick: 1, // powers of ten only
              },
            })}
          />
        )}
      </Section>
    </Stack>
  );
}
