import {
  ActionIcon,
  Button,
  Card,
  Group,
  NumberInput,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Title,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconPlus, IconTimeline, IconX } from "@tabler/icons-react";
import { useState } from "react";

import {
  useCreateAnalysis,
  useCreateAnalysisBatch,
  useEpsilonSuggestion,
} from "../../../../api/queries";
import type { MiddleComplex, NormalizationKind, ZigzagAnalysisConfig } from "../../../../api/types";
import { formatNumber } from "../../../../lib/format";

const MAX_SCALES = 5;

type NewMiddleComplex = Extract<MiddleComplex, "rips" | "union">;
const MIDDLE_DESCRIPTIONS: Record<NewMiddleComplex, string> = {
  rips: "Every candidate counts: what each generation builds and destroys, including the niches joined and the holes opened or filled for a single step by offspring discarded at once.",
  union:
    "Only the parents and the survivors: the offspring discarded at once are left out, and the features of the populations are followed across generations, whatever individuals carry them.",
};

interface ZigzagFormProps {
  experimentId: string;
  runId: string;
  finishedRuns: number;
  onCreated: (analysisId: string) => void;
}

export function ZigzagForm({ experimentId, runId, finishedRuns, onCreated }: ZigzagFormProps) {
  const [normalization, setNormalization] = useState<NormalizationKind>("none");
  const [maxDimension, setMaxDimension] = useState("0");
  const [middle, setMiddle] = useState<NewMiddleComplex>("rips");
  const [representatives, setRepresentatives] = useState(10);
  const [scales, setScales] = useState<number[] | null>(null);
  const [allRuns, setAllRuns] = useState(finishedRuns > 1);
  const suggestion = useEpsilonSuggestion(runId, "survivors", normalization);
  const single = useCreateAnalysis(runId);
  const batch = useCreateAnalysisBatch(experimentId);

  const epsilons = scales ?? suggestion.data?.suggested_scales ?? [];
  const setScale = (index: number, value: number) =>
    setScales(epsilons.map((e, i) => (i === index ? value : e)));
  const distinct = new Set(epsilons).size === epsilons.length;
  const valid = epsilons.length > 0 && distinct && epsilons.every((e) => e > 0);

  const submit = () => {
    const config: ZigzagAnalysisConfig = {
      kind: "zigzag",
      epsilons,
      max_dimension: Number(maxDimension),
      normalization,
      middle,
      representatives,
    };
    const onError = (error: Error) =>
      notifications.show({
        color: "red",
        title: "Could not start the analysis",
        message: error.message,
      });
    if (allRuns) {
      batch.mutate(config, {
        onSuccess: (created) => {
          const own = created.find((a) => a.run_id === runId) ?? created[0];
          if (own) onCreated(own.id);
        },
        onError,
      });
    } else {
      single.mutate(config, { onSuccess: (analysis) => onCreated(analysis.id), onError });
    }
  };

  return (
    <Card withBorder padding="lg">
      <Stack gap="md">
        <div>
          <Title order={4}>Zigzag across generations</Title>
          <Text size="sm" c="dimmed">
            Follows components (niches) and loops of the population through P₀ → R₁ ← P₁ → R₂ ← … at
            fixed scales, and attributes every birth and death either to variation (offspring
            inserted) or to selection (individuals removed).
          </Text>
        </div>
        <Stack gap={6}>
          <Text size="sm" fw={500}>
            Scales ε (edge length)
          </Text>
          <Group gap="xs">
            {epsilons.map((value, index) => (
              <Group key={index} gap={2} wrap="nowrap">
                <NumberInput
                  aria-label={`Scale ${index + 1}`}
                  w={110}
                  min={0}
                  step={0.01}
                  decimalScale={6}
                  value={value}
                  onChange={(v) => typeof v === "number" && setScale(index, v)}
                />
                {epsilons.length > 1 && (
                  <ActionIcon
                    variant="subtle"
                    color="gray"
                    aria-label={`Remove scale ${index + 1}`}
                    onClick={() => setScales(epsilons.filter((_, i) => i !== index))}
                  >
                    <IconX size={14} />
                  </ActionIcon>
                )}
              </Group>
            ))}
            {epsilons.length < MAX_SCALES && (
              <Button
                variant="subtle"
                size="xs"
                leftSection={<IconPlus size={14} />}
                onClick={() => setScales([...epsilons, (epsilons.at(-1) ?? 0.1) * 1.5])}
              >
                Add scale
              </Button>
            )}
          </Group>
          <Text size="xs" c={distinct ? "dimmed" : "red"}>
            {!distinct
              ? "Scales must be distinct."
              : suggestion.data
                ? `Suggested as 1, 1.5 and 2 × the population's median nearest-neighbour spacing (${formatNumber(
                    suggestion.data.median_nearest_neighbour,
                  )}). Larger scales merge niches; the cost grows quickly with ε and with H₁/H₂.`
                : "Computing the scale of the population…"}
          </Text>
        </Stack>
        <SimpleGrid cols={{ base: 1, sm: 3 }}>
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              Homology
            </Text>
            <SegmentedControl
              value={maxDimension}
              onChange={setMaxDimension}
              data={[
                { value: "0", label: "H₀" },
                { value: "1", label: "H₀–H₁" },
                { value: "2", label: "H₀–H₂" },
              ]}
            />
          </Stack>
          <Select
            label="Normalisation"
            allowDeselect={false}
            value={normalization}
            onChange={(v) => {
              if (!v) return;
              setNormalization(v as NormalizationKind);
              setScales(null);
            }}
            data={[
              { value: "none", label: "None (raw objectives)" },
              { value: "ideal_nadir", label: "Fixed: ideal → 0, nadir → 1" },
            ]}
          />
          <NumberInput
            label="Representatives per dimension"
            description="Longest bars whose cycles are kept"
            min={0}
            max={50}
            value={representatives}
            onChange={(v) => typeof v === "number" && setRepresentatives(v)}
          />
        </SimpleGrid>
        <Select
          label="Complex at Rₜ (parents with their offspring)"
          allowDeselect={false}
          value={middle}
          onChange={(v) => v && setMiddle(v as NewMiddleComplex)}
          data={[
            { value: "rips", label: "Vietoris–Rips of every candidate" },
            { value: "union", label: "Union VR(Pₜ₋₁ ∪ Pₜ), without discarded offspring" },
          ]}
          description={MIDDLE_DESCRIPTIONS[middle]}
        />
        <Switch
          label={`Analyse every finished run of the experiment (${finishedRuns}) as one batch`}
          description="Enables the across-run summary (median and quartiles per generation) and the comparison between experiments"
          checked={allRuns}
          disabled={finishedRuns < 2}
          onChange={(event) => setAllRuns(event.currentTarget.checked)}
        />
        <Group justify="flex-end">
          <Button
            leftSection={<IconTimeline size={16} />}
            disabled={!valid}
            loading={single.isPending || batch.isPending}
            onClick={submit}
          >
            Compute
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}
