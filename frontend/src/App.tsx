import {
  ActionIcon,
  Anchor,
  AppShell,
  Button,
  Container,
  Group,
  Text,
  Title,
  Tooltip,
  useComputedColorScheme,
  useMantineColorScheme,
} from "@mantine/core";
import { IconApi, IconMoon, IconPlus, IconSun } from "@tabler/icons-react";
import { Link, NavLink, Navigate, Route, Routes } from "react-router";

import { ComparePage } from "./features/compare/ComparePage";
import { ExperimentDetailPage } from "./features/experiments/ExperimentDetailPage";
import { ExperimentListPage } from "./features/experiments/ExperimentListPage";
import { NewExperimentPage } from "./features/experiments/NewExperimentPage";
import classes from "./App.module.css";

function ColorSchemeToggle() {
  const { setColorScheme } = useMantineColorScheme();
  const scheme = useComputedColorScheme("light");
  const next = scheme === "dark" ? "light" : "dark";
  return (
    <Tooltip label={`Switch to ${next} mode`}>
      <ActionIcon
        variant="subtle"
        color="gray"
        aria-label={`Switch to ${next} mode`}
        onClick={() => setColorScheme(next)}
      >
        {scheme === "dark" ? <IconSun size={18} /> : <IconMoon size={18} />}
      </ActionIcon>
    </Tooltip>
  );
}

function NotFound() {
  return (
    <Container py="xl">
      <Title order={2}>Page not found</Title>
      <Anchor component={Link} to="/experiments">
        Back to experiments
      </Anchor>
    </Container>
  );
}

export function App() {
  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="lg" wrap="nowrap">
            <Anchor component={Link} to="/experiments" underline="never" c="inherit">
              <Group gap={8} wrap="nowrap">
                <img src="/favicon.svg" alt="" width={24} height={24} />
                <Text fw={700}>ESPHEA</Text>
              </Group>
            </Anchor>
            <Group gap={4} visibleFrom="xs">
              <NavLink to="/experiments" end className={classes.link}>
                Experiments
              </NavLink>
              <NavLink to="/compare" className={classes.link}>
                Compare
              </NavLink>
            </Group>
          </Group>
          <Group gap="xs" wrap="nowrap">
            <Button
              component={Link}
              to="/experiments/new"
              size="xs"
              leftSection={<IconPlus size={14} />}
            >
              New experiment
            </Button>
            <Tooltip label="API documentation">
              <ActionIcon
                component="a"
                href="/api/docs"
                target="_blank"
                variant="subtle"
                color="gray"
                aria-label="API documentation"
              >
                <IconApi size={18} />
              </ActionIcon>
            </Tooltip>
            <ColorSchemeToggle />
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <Routes>
          <Route path="/" element={<Navigate to="/experiments" replace />} />
          <Route path="/experiments" element={<ExperimentListPage />} />
          <Route path="/experiments/new" element={<NewExperimentPage />} />
          <Route path="/experiments/:experimentId" element={<ExperimentDetailPage />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </AppShell.Main>
    </AppShell>
  );
}
