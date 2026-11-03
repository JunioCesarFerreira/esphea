import {
  ActionIcon,
  Alert,
  Card,
  Chip,
  Group,
  Select,
  SimpleGrid,
  Slider,
  Stack,
  Switch,
  Text,
  Tooltip,
} from "@mantine/core";
import { IconInfoCircle, IconPlayerPause, IconPlayerPlay } from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";

import type { LiveFront } from "../../../api/events";
import { useParetoFront, useSnapshot, useStoredGenerations } from "../../../api/queries";
import type { Experiment, GenerationSnapshot } from "../../../api/types";
import { PlotlyChart } from "../../../components/PlotlyChart";
import { useChartTheme } from "../../../hooks/useChartTheme";
import { formatInteger } from "../../../lib/format";
import {
  LAYER_LABELS,
  type Layer,
  liveFrontTraces,
  liveParallelTrace,
  objectiveSpaceLayout,
  objectiveSpaceTraces,
  parallelCoordinatesTrace,
  baseLayout,
} from "../../../lib/plots";

const PLAY_INTERVAL_MS = 120;
const ALL_LAYERS: Layer[] = ["population", "offspring", "discarded", "front"];

function count(values: boolean[] | undefined): number {
  return values?.filter(Boolean).length ?? 0;
}

function GenerationStats({ snapshot }: { snapshot: GenerationSnapshot }) {
  const offspring = snapshot.offspring;
  const survivorsFromOffspring = count(offspring?.survived);
  const firstFront = [...snapshot.population.rank, ...(offspring?.rank ?? [])].filter(
    (r) => r === 0,
  ).length;
  const stats: [string, string, string][] = offspring
    ? [
        [
          "Offspring survival",
          `${formatInteger(survivorsFromOffspring)} / ${formatInteger(offspring.F.length)}`,
          "Children of Qₜ selected into Pₜ₊₁",
        ],
        [
          "Parents used",
          `${formatInteger(snapshot.population.times_selected.filter((n) => n > 0).length)} / ${formatInteger(snapshot.population.F.length)}`,
          "Members of Pₜ chosen for at least one mating (selection pressure)",
        ],
        ["First front of Pₜ₊₁", formatInteger(firstFront), "Survivors with non-domination rank 0"],
        [
          "Mutated offspring",
          formatInteger(count(offspring.mutated)),
          "Children changed by polynomial mutation",
        ],
      ]
    : [
        [
          "Initial population",
          formatInteger(snapshot.population.F.length),
          "Uniform random sample, ranked",
        ],
      ];
  return (
    <SimpleGrid cols={{ base: 2, sm: 4 }}>
      {stats.map(([label, value, hint]) => (
        <Tooltip key={label} label={hint}>
          <Card withBorder padding="sm">
            <Text size="xs" c="dimmed">
              {label}
            </Text>
            <Text fw={600} className="tabular">
              {value}
            </Text>
          </Card>
        </Tooltip>
      ))}
    </SimpleGrid>
  );
}

interface ObjectiveSpacePanelProps {
  experiment: Experiment;
  liveFronts: Record<string, LiveFront>;
}

export function ObjectiveSpacePanel({ experiment, liveFronts }: ObjectiveSpacePanelProps) {
  const theme = useChartTheme();
  const nObj = experiment.config.problem.n_obj;
  const [runId, setRunId] = useState<string | null>(experiment.runs[0]?.id ?? null);
  const run = experiment.runs.find((r) => r.id === runId);
  const running = run?.status === "running";
  const [followLive, setFollowLive] = useState(true);
  const [layers, setLayers] = useState<Set<Layer>>(new Set(ALL_LAYERS));
  const [position, setPosition] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);

  const stored = useStoredGenerations(runId, running);
  const generations = useMemo(() => stored.data?.generations ?? [], [stored.data]);
  const lastIndex = generations.length - 1;
  const index = position === null ? lastIndex : Math.min(position, lastIndex);
  const generation = index >= 0 ? (generations[index] ?? null) : null;
  const snapshot = useSnapshot(runId, generation);
  const front = useParetoFront(experiment.id);
  const live = running && followLive ? liveFronts[runId ?? ""] : undefined;

  useEffect(() => {
    if (!playing) return;
    const timer = setInterval(() => {
      setPosition((current) => {
        const next = (current ?? lastIndex) + 1;
        if (next >= lastIndex) setPlaying(false);
        return Math.min(next, lastIndex);
      });
    }, PLAY_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [playing, lastIndex]);

  const togglePlay = () => {
    if (!playing && index >= lastIndex) setPosition(0);
    setPlaying(!playing);
  };

  const truePoints = front.data?.points ?? null;
  const chart = useMemo(() => {
    const parcoordsLayout = baseLayout(theme, { margin: { l: 48, r: 48, t: 48, b: 24 } });
    if (live) {
      if (nObj > 3) {
        return { data: [liveParallelTrace(live.front, theme)], layout: parcoordsLayout };
      }
      const traces = liveFrontTraces(live.front, truePoints, layers.has("front"), theme);
      return { data: traces, layout: objectiveSpaceLayout(theme, nObj, `${runId}`, traces) };
    }
    const data = snapshot.data;
    if (!data) return null;
    if (nObj > 3) {
      return { data: [parallelCoordinatesTrace(data, layers, theme)], layout: parcoordsLayout };
    }
    const traces = objectiveSpaceTraces(data, truePoints, layers, theme);
    return { data: traces, layout: objectiveSpaceLayout(theme, nObj, `${runId}`, traces) };
  }, [live, snapshot.data, truePoints, layers, theme, nObj, runId]);

  const runOptions = experiment.runs.map((r) => ({
    value: r.id,
    label: `Run ${r.index + 1} · seed ${r.seed} · ${r.status}`,
  }));

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-end" wrap="wrap">
        <Select
          label="Run"
          data={runOptions}
          value={runId}
          onChange={setRunId}
          allowDeselect={false}
          w={320}
        />
        <Chip.Group
          multiple
          value={[...layers]}
          onChange={(values) => setLayers(new Set(values as Layer[]))}
        >
          <Group gap={6}>
            {ALL_LAYERS.filter((layer) => nObj <= 3 || layer !== "front").map((layer) => (
              <Chip key={layer} value={layer} size="sm" variant="outline">
                {LAYER_LABELS[layer]}
              </Chip>
            ))}
          </Group>
        </Chip.Group>
      </Group>

      {running && (
        <Switch
          label="Follow the run live (first front streamed every few hundred ms)"
          checked={followLive}
          onChange={(event) => setFollowLive(event.currentTarget.checked)}
        />
      )}

      {!live && (
        <Group gap="md" wrap="nowrap" align="center">
          <ActionIcon
            variant="light"
            size="lg"
            aria-label={playing ? "Pause" : "Play generations"}
            disabled={generations.length < 2}
            onClick={togglePlay}
          >
            {playing ? <IconPlayerPause size={18} /> : <IconPlayerPlay size={18} />}
          </ActionIcon>
          <Slider
            style={{ flex: 1 }}
            min={0}
            max={Math.max(lastIndex, 0)}
            value={Math.max(index, 0)}
            disabled={generations.length < 2}
            label={(i) => `generation ${generations[i] ?? 0}`}
            onChange={(value) => {
              setPlaying(false);
              setPosition(value);
            }}
          />
          <Text size="sm" w={150} ta="right" className="tabular">
            Generation {generation ?? "—"} / {experiment.n_gen}
          </Text>
        </Group>
      )}

      {live && (
        <Text size="sm" c="dimmed">
          Live · generation {live.generation} / {experiment.n_gen}
        </Text>
      )}

      {!live && !stored.isPending && generations.length === 0 && (
        <Alert icon={<IconInfoCircle size={16} />} color="gray">
          {experiment.config.snapshots.enabled
            ? "No generation stored yet for this run."
            : "Snapshots are disabled for this experiment; only the live front is available while running."}
        </Alert>
      )}

      {chart && (
        <Card withBorder padding="xs">
          <PlotlyChart
            data={chart.data}
            layout={chart.layout}
            height={nObj === 3 ? 600 : 520}
            ariaLabel={`Objective space of run ${run ? run.index + 1 : ""}, generation ${live?.generation ?? generation ?? ""}`}
          />
          {nObj <= 3 && !live && (
            <Text size="xs" c="dimmed" px="sm" pb="xs">
              Filled markers survived into the next generation; open markers were discarded. Hover a
              point to see its rank and lineage.
            </Text>
          )}
        </Card>
      )}

      {!live && snapshot.data && <GenerationStats snapshot={snapshot.data} />}
    </Stack>
  );
}
