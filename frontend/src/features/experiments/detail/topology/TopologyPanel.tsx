import {
  ActionIcon,
  Alert,
  Button,
  Group,
  Progress,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconInfoCircle, IconPlus, IconTrash } from "@tabler/icons-react";
import { useState } from "react";

import { useAnalyses, useDeleteAnalysis } from "../../../../api/queries";
import { isActive, type Analysis, type Experiment } from "../../../../api/types";
import { StatusBadge } from "../../../../components/StatusBadge";
import { ANALYSIS_KIND_LABELS, describeAnalysis } from "../../../../lib/analysisModel";
import { TopologyAnalysisForm } from "./AnalysisForm";
import { AnalysisResults } from "./AnalysisResults";
import { ZigzagForm } from "./ZigzagForm";
import { ZigzagResults } from "./ZigzagResults";

type Kind = keyof typeof ANALYSIS_KIND_LABELS;

function Progressing({ analysis }: { analysis: Analysis }) {
  const share = analysis.total > 0 ? analysis.progress / analysis.total : 0;
  return (
    <Stack gap={4}>
      <Text size="sm">
        {analysis.status === "queued"
          ? "Waiting for a worker…"
          : analysis.kind === "zigzag"
            ? `Computing the zigzag at each scale (${analysis.progress} / ${analysis.total})`
            : `Computing generation barcodes (${analysis.progress} / ${analysis.total})`}
      </Text>
      <Progress value={share * 100} animated />
    </Stack>
  );
}

export function TopologyPanel({ experiment }: { experiment: Experiment }) {
  const finished = experiment.runs.filter(
    (run) => run.status === "completed" || run.status === "cancelled",
  );
  const [runId, setRunId] = useState<string | null>(finished[0]?.id ?? null);
  const analyses = useAnalyses(runId);
  const [chosen, setChosen] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [kind, setKind] = useState<Kind>("zigzag");
  const remove = useDeleteAnalysis(runId ?? "");

  if (finished.length === 0) {
    return (
      <Alert icon={<IconInfoCircle size={16} />} color="gray">
        Persistent-homology analyses are computed from the stored generations of finished runs.
      </Alert>
    );
  }

  const onCreated = (id: string) => {
    setChosen(id);
    setCreating(false);
  };

  const list = analyses.data ?? [];
  const selected = list.find((a) => a.id === chosen) ?? list[0];
  const showForm = creating || (!analyses.isPending && list.length === 0);

  return (
    <Stack gap="md">
      <Group align="flex-end" wrap="wrap">
        <Select
          label="Run"
          w={300}
          allowDeselect={false}
          value={runId}
          onChange={(value) => {
            setRunId(value);
            setChosen(null);
            setCreating(false);
          }}
          data={finished.map((run) => ({
            value: run.id,
            label: `Run ${run.index + 1} · seed ${run.seed}`,
          }))}
        />
        {list.length > 0 && (
          <Select
            label="Analysis"
            style={{ flex: 1, minWidth: 320 }}
            allowDeselect={false}
            value={selected?.id ?? null}
            onChange={(value) => {
              setChosen(value);
              setCreating(false);
            }}
            data={list.map((a) => ({ value: a.id, label: `${describeAnalysis(a)} · ${a.status}` }))}
          />
        )}
        {selected && !showForm && (
          <Tooltip label="Delete this analysis">
            <ActionIcon
              variant="subtle"
              color="gray"
              size="lg"
              aria-label="Delete this analysis"
              disabled={isActive(selected.status)}
              loading={remove.isPending}
              onClick={() =>
                remove.mutate(selected.id, {
                  onSuccess: () => setChosen(null),
                  onError: (error) => notifications.show({ color: "red", message: error.message }),
                })
              }
            >
              <IconTrash size={18} />
            </ActionIcon>
          </Tooltip>
        )}
        {!showForm && (
          <Button
            variant="light"
            leftSection={<IconPlus size={16} />}
            onClick={() => setCreating(true)}
          >
            New analysis
          </Button>
        )}
      </Group>

      {showForm && runId && (
        <Stack gap="sm">
          <SegmentedControl
            value={kind}
            onChange={(value) => setKind(value as Kind)}
            data={Object.entries(ANALYSIS_KIND_LABELS).map(([value, label]) => ({ value, label }))}
          />
          {kind === "zigzag" ? (
            <ZigzagForm
              key={runId}
              experimentId={experiment.id}
              runId={runId}
              finishedRuns={finished.length}
              onCreated={onCreated}
            />
          ) : (
            <TopologyAnalysisForm key={runId} runId={runId} onCreated={onCreated} />
          )}
        </Stack>
      )}

      {!showForm && selected && (
        <>
          <Group gap="xs">
            <StatusBadge status={selected.status} />
            {selected.attempt > 1 && (
              <Text size="xs" c="dimmed">
                Attempt {selected.attempt}
              </Text>
            )}
          </Group>
          {isActive(selected.status) && <Progressing analysis={selected} />}
          {selected.status === "failed" && (
            <Alert color="red" title="The analysis failed">
              {selected.error}
            </Alert>
          )}
          {selected.status === "completed" &&
            (selected.config.kind === "zigzag" ? (
              <ZigzagResults
                key={selected.id}
                analysis={selected}
                config={selected.config}
                nObj={experiment.config.problem.n_obj}
              />
            ) : (
              <AnalysisResults key={selected.id} analysis={selected} config={selected.config} />
            ))}
        </>
      )}
    </Stack>
  );
}
