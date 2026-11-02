import {
  Anchor,
  Badge,
  Breadcrumbs,
  Code,
  Container,
  Group,
  Progress,
  Stack,
  Tabs,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { IconChartLine, IconCode, IconList, IconChartScatter } from "@tabler/icons-react";
import { Link, useParams } from "react-router";

import { useExperimentEvents } from "../../api/events";
import { useExperiment } from "../../api/queries";
import { isActive, type Experiment } from "../../api/types";
import { QueryState } from "../../components/QueryState";
import { StatusBadge } from "../../components/StatusBadge";
import { describeExperiment } from "../../lib/configModel";
import { formatDateTime, formatInteger } from "../../lib/format";
import { ConvergencePanel } from "./detail/ConvergencePanel";
import { ObjectiveSpacePanel } from "./detail/ObjectiveSpacePanel";
import { RunsPanel } from "./detail/RunsPanel";
import { ExperimentActions } from "./ExperimentActions";

function Header({ experiment, connected }: { experiment: Experiment; connected: boolean }) {
  const active = isActive(experiment.status);
  return (
    <Stack gap="xs">
      <Breadcrumbs>
        <Anchor component={Link} to="/experiments" size="sm">
          Experiments
        </Anchor>
        <Text size="sm">{experiment.name}</Text>
      </Breadcrumbs>
      <Group justify="space-between" wrap="nowrap">
        <Group gap="sm">
          <Title order={2}>{experiment.name}</Title>
          <StatusBadge status={experiment.status} />
          {active && (
            <Tooltip label={connected ? "Receiving live updates" : "Reconnecting to live updates…"}>
              <Badge variant="dot" color={connected ? "green" : "gray"}>
                {connected ? "Live" : "Offline"}
              </Badge>
            </Tooltip>
          )}
        </Group>
        <ExperimentActions
          id={experiment.id}
          name={experiment.name}
          status={experiment.status}
          afterDelete="/experiments"
        />
      </Group>
      <Text size="sm" c="dimmed">
        {describeExperiment(experiment.config)} · population {formatInteger(experiment.pop_size)} ·{" "}
        {formatInteger(experiment.n_gen)} generations · {experiment.n_runs} run(s) · created{" "}
        {formatDateTime(experiment.created_at)}
      </Text>
      {active && <Progress value={experiment.progress * 100} size="sm" animated />}
    </Stack>
  );
}

function Detail({ experiment }: { experiment: Experiment }) {
  const live = isActive(experiment.status);
  const { connected, liveFronts } = useExperimentEvents(experiment.id, live);
  return (
    <Stack gap="lg">
      <Header experiment={experiment} connected={connected} />
      <Tabs defaultValue="objective-space" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="objective-space" leftSection={<IconChartScatter size={16} />}>
            Objective space
          </Tabs.Tab>
          <Tabs.Tab value="convergence" leftSection={<IconChartLine size={16} />}>
            Convergence
          </Tabs.Tab>
          <Tabs.Tab value="runs" leftSection={<IconList size={16} />}>
            Runs
          </Tabs.Tab>
          <Tabs.Tab value="configuration" leftSection={<IconCode size={16} />}>
            Configuration
          </Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="objective-space" pt="md">
          <ObjectiveSpacePanel experiment={experiment} liveFronts={liveFronts} />
        </Tabs.Panel>
        <Tabs.Panel value="convergence" pt="md">
          <ConvergencePanel experiment={experiment} live={live} />
        </Tabs.Panel>
        <Tabs.Panel value="runs" pt="md">
          <RunsPanel experiment={experiment} live={live} />
        </Tabs.Panel>
        <Tabs.Panel value="configuration" pt="md">
          <Code block>{JSON.stringify(experiment.config, null, 2)}</Code>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

export function ExperimentDetailPage() {
  const { experimentId = "" } = useParams();
  const { data, isPending, error } = useExperiment(experimentId);
  return (
    <Container size="xl">
      <QueryState isPending={isPending} error={error}>
        {data && <Detail experiment={data} />}
      </QueryState>
    </Container>
  );
}
