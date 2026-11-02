import {
  Alert,
  Button,
  Card,
  Container,
  Grid,
  Group,
  List,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconPlayerPlay, IconRestore } from "@tabler/icons-react";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { ApiError } from "../../api/client";
import { useCatalog, useCreateExperiment, useExperiment, usePreview } from "../../api/queries";
import type { Catalog, ExperimentConfig, Preview } from "../../api/types";
import { QueryState } from "../../components/QueryState";
import { defaultConfig, duplicateConfig, issuesByPath } from "../../lib/configModel";
import { formatBytes, formatInteger } from "../../lib/format";
import { IssuesContext } from "./form/issues";
import { ExperimentForm } from "./form/ExperimentForm";

const LARGE_STORAGE_BYTES = 1024 ** 3;

function DerivedSummary({
  config,
  preview,
}: {
  config: ExperimentConfig;
  preview: Preview | undefined;
}) {
  const rows: [string, string][] = preview
    ? [
        ["Decision variables", String(preview.n_var)],
        ["Objectives", String(preview.n_obj)],
        ...(preview.n_reference_directions !== null && preview.n_reference_directions !== undefined
          ? ([["Reference directions", formatInteger(preview.n_reference_directions)]] as [
              string,
              string,
            ][])
          : []),
        ["Population size", formatInteger(preview.pop_size)],
        [
          "Evaluations (all runs)",
          formatInteger(preview.pop_size * (config.n_gen + 1) * config.n_runs),
        ],
        ["Snapshot storage / run", `≤ ${formatBytes(preview.estimated_snapshot_bytes_per_run)}`],
        ["Snapshot storage total", `≤ ${formatBytes(preview.estimated_snapshot_bytes_total)}`],
      ]
    : [];
  return (
    <Table variant="vertical" withTableBorder={false} verticalSpacing={6}>
      <Table.Tbody>
        {rows.map(([label, value]) => (
          <Table.Tr key={label}>
            <Table.Th fw={400} c="dimmed" w="60%">
              {label}
            </Table.Th>
            <Table.Td ta="right" className="tabular">
              {value}
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}

function Editor({ catalog, initial }: { catalog: Catalog; initial: ExperimentConfig }) {
  const navigate = useNavigate();
  const [config, setConfig] = useState(initial);
  const [debounced] = useDebouncedValue(config, 300);
  const preview = usePreview(debounced);
  const create = useCreateExperiment();

  const validationError = preview.error instanceof ApiError ? preview.error : null;
  const issues = useMemo(() => issuesByPath(validationError?.issues ?? []), [validationError]);
  const general = issues.get("") ?? [];
  const stale = debounced !== config || preview.isFetching;
  const invalid = validationError !== null;
  const storage = preview.data?.estimated_snapshot_bytes_total ?? 0;

  const submit = () =>
    create.mutate(config, {
      onSuccess: (experiment) => {
        notifications.show({
          color: "green",
          message: `Started ${experiment.n_runs} run(s) of “${experiment.name}”`,
        });
        void navigate(`/experiments/${experiment.id}`);
      },
      onError: (error) =>
        notifications.show({
          color: "red",
          title: "Could not create the experiment",
          message: error.message,
        }),
    });

  return (
    <IssuesContext.Provider value={issues}>
      <Grid gap="md">
        <Grid.Col span={{ base: 12, md: 8 }}>
          <ExperimentForm config={config} catalog={catalog} onChange={setConfig} />
        </Grid.Col>
        <Grid.Col span={{ base: 12, md: 4 }}>
          <Card withBorder padding="lg" pos="sticky" top={72}>
            <Stack gap="md">
              <Title order={4}>Summary</Title>
              <DerivedSummary config={config} preview={preview.data} />
              {general.length > 0 && (
                <Alert
                  color="red"
                  icon={<IconAlertTriangle size={16} />}
                  title="Invalid configuration"
                >
                  <List size="sm">
                    {general.map((message) => (
                      <List.Item key={message}>{message}</List.Item>
                    ))}
                  </List>
                </Alert>
              )}
              {invalid && general.length === 0 && (
                <Text size="sm" c="red">
                  Fix the highlighted fields to continue.
                </Text>
              )}
              {storage > LARGE_STORAGE_BYTES && (
                <Alert color="yellow" icon={<IconAlertTriangle size={16} />}>
                  Large snapshot volume. Consider storing every N-th generation, float32 or
                  objectives only.
                </Alert>
              )}
              <Group grow>
                <Button
                  variant="default"
                  leftSection={<IconRestore size={16} />}
                  onClick={() => setConfig(defaultConfig(catalog, config.algorithm.name))}
                >
                  Defaults
                </Button>
                <Button
                  leftSection={<IconPlayerPlay size={16} />}
                  disabled={invalid || stale || config.name.trim() === ""}
                  loading={create.isPending}
                  onClick={submit}
                >
                  Run
                </Button>
              </Group>
            </Stack>
          </Card>
        </Grid.Col>
      </Grid>
    </IssuesContext.Provider>
  );
}

export function NewExperimentPage() {
  const [params] = useSearchParams();
  const sourceId = params.get("from");
  const catalog = useCatalog();
  const source = useExperiment(sourceId ?? "", sourceId !== null);
  const waitingForSource = sourceId !== null && source.isPending;

  return (
    <Container size="xl">
      <Title order={2} mb="md">
        {sourceId ? "Duplicate experiment" : "New experiment"}
      </Title>
      <QueryState
        isPending={catalog.isPending || waitingForSource}
        error={catalog.error ?? (sourceId ? source.error : null)}
      >
        {catalog.data && (
          <Editor
            key={sourceId ?? "new"}
            catalog={catalog.data}
            initial={
              sourceId && source.data
                ? duplicateConfig(source.data.config)
                : defaultConfig(catalog.data)
            }
          />
        )}
      </QueryState>
    </Container>
  );
}
