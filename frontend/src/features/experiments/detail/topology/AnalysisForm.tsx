import {
  Anchor,
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
import { IconTopologyStar3 } from "@tabler/icons-react";
import { useState } from "react";

import { useCreateAnalysis, useEpsilonSuggestion } from "../../../../api/queries";
import type { NormalizationKind, PointCloudKind } from "../../../../api/types";
import { formatNumber } from "../../../../lib/format";

const POINT_CLOUDS: { value: PointCloudKind; label: string }[] = [
  { value: "survivors", label: "Survivors Pₜ" },
  { value: "merged", label: "Candidates Pₜ₋₁ ∪ Qₜ₋₁" },
  { value: "first_front", label: "First front" },
];

const NORMALIZATIONS: { value: NormalizationKind; label: string }[] = [
  { value: "none", label: "None (raw objectives)" },
  { value: "ideal_nadir", label: "Fixed: ideal → 0, nadir → 1" },
  { value: "min_max", label: "Per generation: min–max" },
];

export function TopologyAnalysisForm({
  runId,
  onCreated,
}: {
  runId: string;
  onCreated: (id: string) => void;
}) {
  const [pointCloud, setPointCloud] = useState<PointCloudKind>("survivors");
  const [normalization, setNormalization] = useState<NormalizationKind>("none");
  const [maxDimension, setMaxDimension] = useState("1");
  const [epsilon, setEpsilon] = useState<number | null>(null);
  const [matrix, setMatrix] = useState(false);
  const suggestion = useEpsilonSuggestion(runId, pointCloud, normalization);
  const create = useCreateAnalysis(runId);

  const suggested = suggestion.data?.suggested_max_epsilon;
  const maxEpsilon = epsilon ?? suggested ?? null;

  const submit = () => {
    if (maxEpsilon === null) return;
    create.mutate(
      {
        kind: "topology",
        point_cloud: pointCloud,
        normalization,
        max_dimension: Number(maxDimension),
        max_epsilon: maxEpsilon,
        distance_matrix: matrix,
      },
      {
        onSuccess: (analysis) => onCreated(analysis.id),
        onError: (error) =>
          notifications.show({
            color: "red",
            title: "Could not start the analysis",
            message: error.message,
          }),
      },
    );
  };

  return (
    <Card withBorder padding="lg">
      <Stack gap="md">
        <div>
          <Title order={4}>Barcodes per generation</Title>
          <Text size="sm" c="dimmed">
            Vietoris–Rips barcodes of the population in objective space for every stored generation,
            and the distances between them.
          </Text>
        </div>
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Point cloud
          </Text>
          <SegmentedControl
            value={pointCloud}
            onChange={(value) => setPointCloud(value as PointCloudKind)}
            data={POINT_CLOUDS}
          />
        </Stack>
        <SimpleGrid cols={{ base: 1, sm: 2 }}>
          <Select
            label="Normalisation"
            data={NORMALIZATIONS}
            value={normalization}
            allowDeselect={false}
            onChange={(value) => value && setNormalization(value as NormalizationKind)}
          />
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
        </SimpleGrid>
        <NumberInput
          label="Maximum scale ε (edge length)"
          description={
            suggestion.data ? (
              <>
                Largest cloud diameter {formatNumber(suggestion.data.max_diameter)} · median
                nearest-neighbour spacing {formatNumber(suggestion.data.median_nearest_neighbour)}
                {epsilon !== null && suggested !== undefined && (
                  <>
                    {" · "}
                    <Anchor
                      component="button"
                      type="button"
                      size="xs"
                      onClick={() => setEpsilon(null)}
                    >
                      use suggested {formatNumber(suggested)}
                    </Anchor>
                  </>
                )}
              </>
            ) : (
              "Computing the scale of the point clouds…"
            )
          }
          error={suggestion.error?.message}
          min={0}
          step={0.05}
          decimalScale={6}
          value={maxEpsilon ?? ""}
          onChange={(value) => setEpsilon(typeof value === "number" ? value : null)}
        />
        <Switch
          label="Distance matrix between generations (up to 100, slower)"
          checked={matrix}
          onChange={(event) => setMatrix(event.currentTarget.checked)}
        />
        {maxDimension === "2" && (
          <Text size="xs" c="dimmed">
            H₂ is considerably more expensive to compute.
          </Text>
        )}
        <Group justify="flex-end">
          <Button
            leftSection={<IconTopologyStar3 size={16} />}
            disabled={maxEpsilon === null || maxEpsilon <= 0}
            loading={create.isPending}
            onClick={submit}
          >
            Compute
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}
