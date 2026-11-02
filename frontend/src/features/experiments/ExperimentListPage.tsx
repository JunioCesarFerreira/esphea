import {
  Anchor,
  Button,
  Card,
  Container,
  Group,
  Progress,
  Stack,
  Table,
  Text,
  Title,
} from "@mantine/core";
import { IconFlask, IconPlus } from "@tabler/icons-react";
import { Link } from "react-router";

import { useExperiments } from "../../api/queries";
import type { ExperimentSummary } from "../../api/types";
import { QueryState } from "../../components/QueryState";
import { StatusBadge } from "../../components/StatusBadge";
import { ALGORITHM_LABELS, PROBLEM_LABELS } from "../../lib/configModel";
import { formatDateTime, formatInteger } from "../../lib/format";
import { ExperimentActions } from "./ExperimentActions";

function EmptyState() {
  return (
    <Card withBorder padding="xl">
      <Stack align="center" gap="sm">
        <IconFlask size={36} stroke={1.5} />
        <Title order={4}>No experiments yet</Title>
        <Text c="dimmed" size="sm" ta="center" maw={420}>
          Configure NSGA-II or NSGA-III on DTLZ2, run several seeds in parallel and explore how
          parents, offspring and survivors move through objective space.
        </Text>
        <Button component={Link} to="/experiments/new" leftSection={<IconPlus size={16} />}>
          Create the first experiment
        </Button>
      </Stack>
    </Card>
  );
}

function Row({ experiment }: { experiment: ExperimentSummary }) {
  return (
    <Table.Tr>
      <Table.Td>
        <Anchor component={Link} to={`/experiments/${experiment.id}`} fw={500}>
          {experiment.name}
        </Anchor>
      </Table.Td>
      <Table.Td>
        {ALGORITHM_LABELS[experiment.algorithm as keyof typeof ALGORITHM_LABELS] ??
          experiment.algorithm}
      </Table.Td>
      <Table.Td>
        {PROBLEM_LABELS[experiment.problem] ?? experiment.problem} · M={experiment.n_obj}
      </Table.Td>
      <Table.Td className="tabular">
        {formatInteger(experiment.pop_size)} × {formatInteger(experiment.n_gen)}
      </Table.Td>
      <Table.Td className="tabular">{experiment.n_runs}</Table.Td>
      <Table.Td>
        <StatusBadge status={experiment.status} />
      </Table.Td>
      <Table.Td miw={120}>
        <Progress
          value={experiment.progress * 100}
          size="sm"
          aria-label={`${Math.round(experiment.progress * 100)}% complete`}
        />
      </Table.Td>
      <Table.Td c="dimmed">{formatDateTime(experiment.created_at)}</Table.Td>
      <Table.Td>
        <ExperimentActions id={experiment.id} name={experiment.name} status={experiment.status} />
      </Table.Td>
    </Table.Tr>
  );
}

export function ExperimentListPage() {
  const { data, isPending, error } = useExperiments();
  return (
    <Container size="xl">
      <Group justify="space-between" mb="md">
        <Title order={2}>Experiments</Title>
        <Button component={Link} to="/experiments/new" leftSection={<IconPlus size={16} />}>
          New experiment
        </Button>
      </Group>
      <QueryState isPending={isPending} error={error}>
        {data && data.length === 0 ? (
          <EmptyState />
        ) : (
          <Card withBorder padding={0}>
            <Table.ScrollContainer minWidth={900}>
              <Table highlightOnHover verticalSpacing="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Name</Table.Th>
                    <Table.Th>Algorithm</Table.Th>
                    <Table.Th>Problem</Table.Th>
                    <Table.Th>Pop. × gen.</Table.Th>
                    <Table.Th>Runs</Table.Th>
                    <Table.Th>Status</Table.Th>
                    <Table.Th>Progress</Table.Th>
                    <Table.Th>Created</Table.Th>
                    <Table.Th aria-label="Actions" />
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {data?.map((experiment) => (
                    <Row key={experiment.id} experiment={experiment} />
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          </Card>
        )}
      </QueryState>
    </Container>
  );
}
