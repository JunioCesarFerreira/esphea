import {
  ActionIcon,
  Alert,
  Button,
  Group,
  Input,
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

const KINDS = Object.keys(ANALYSIS_KIND_LABELS) as Kind[];

/** What the user has picked for one kind of analysis: an analysis to show, or the form. */
interface Selection {
  chosen: string | null;
  creating: boolean;
}

const NO_SELECTION: Selection = { chosen: null, creating: false };

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

function AnalysisView({ analysis, nObj }: { analysis: Analysis; nObj: number }) {
  return (
    <>
      <Group gap="xs">
        <StatusBadge status={analysis.status} />
        {analysis.attempt > 1 && (
          <Text size="xs" c="dimmed">
            Attempt {analysis.attempt}
          </Text>
        )}
      </Group>
      {isActive(analysis.status) && <Progressing analysis={analysis} />}
      {analysis.status === "failed" && (
        <Alert color="red" title="The analysis failed">
          {analysis.error}
        </Alert>
      )}
      {analysis.status === "completed" &&
        (analysis.config.kind === "zigzag" ? (
          <ZigzagResults
            key={analysis.id}
            analysis={analysis}
            config={analysis.config}
            nObj={nObj}
          />
        ) : (
          <AnalysisResults key={analysis.id} analysis={analysis} config={analysis.config} />
        ))}
    </>
  );
}

/** The analyses of one kind for a run: pick one, delete it, or start a new one. */
function AnalysisWorkspace({
  kind,
  experiment,
  runId,
  finishedRuns,
  analyses,
  isPending,
  selection,
  onSelect,
}: {
  kind: Kind;
  experiment: Experiment;
  runId: string;
  finishedRuns: number;
  analyses: Analysis[];
  isPending: boolean;
  selection: Selection;
  onSelect: (selection: Selection) => void;
}) {
  const remove = useDeleteAnalysis(runId);
  const selected = analyses.find((a) => a.id === selection.chosen) ?? analyses[0];
  const showForm = selection.creating || (!isPending && analyses.length === 0);
  const onCreated = (id: string) => onSelect({ chosen: id, creating: false });

  return (
    <Stack gap="md">
      {analyses.length > 0 && (
        <Group align="flex-end" wrap="wrap">
          <Select
            label="Analysis"
            style={{ flex: 1, minWidth: 320 }}
            allowDeselect={false}
            value={showForm ? null : (selected?.id ?? null)}
            placeholder="New analysis"
            onChange={(value) => onSelect({ chosen: value, creating: false })}
            data={analyses.map((a) => ({
              value: a.id,
              label: `${describeAnalysis(a)} · ${a.status}`,
            }))}
          />
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
                    onSuccess: () => onSelect(NO_SELECTION),
                    onError: (error) =>
                      notifications.show({ color: "red", message: error.message }),
                  })
                }
              >
                <IconTrash size={18} />
              </ActionIcon>
            </Tooltip>
          )}
          {showForm ? (
            <Button variant="default" onClick={() => onSelect({ ...selection, creating: false })}>
              Cancel
            </Button>
          ) : (
            <Button
              variant="light"
              leftSection={<IconPlus size={16} />}
              onClick={() => onSelect({ ...selection, creating: true })}
            >
              New analysis
            </Button>
          )}
        </Group>
      )}

      {showForm &&
        (kind === "zigzag" ? (
          <ZigzagForm
            key={runId}
            experimentId={experiment.id}
            runId={runId}
            finishedRuns={finishedRuns}
            onCreated={onCreated}
          />
        ) : (
          <TopologyAnalysisForm key={runId} runId={runId} onCreated={onCreated} />
        ))}

      {!showForm && selected && (
        <AnalysisView analysis={selected} nObj={experiment.config.problem.n_obj} />
      )}
    </Stack>
  );
}

export function TopologyPanel({ experiment }: { experiment: Experiment }) {
  const finished = experiment.runs.filter(
    (run) => run.status === "completed" || run.status === "cancelled",
  );
  const [runId, setRunId] = useState<string | null>(finished[0]?.id ?? null);
  const analyses = useAnalyses(runId);
  const [pickedKind, setPickedKind] = useState<Kind | null>(null);
  const [selections, setSelections] = useState<Record<Kind, Selection>>({
    topology: NO_SELECTION,
    zigzag: NO_SELECTION,
  });

  if (finished.length === 0) {
    return (
      <Alert icon={<IconInfoCircle size={16} />} color="gray">
        Persistent-homology analyses are computed from the stored generations of finished runs.
      </Alert>
    );
  }

  const list = analyses.data ?? [];
  const byKind = (k: Kind) => list.filter((a) => a.config.kind === k);
  // until the user picks a tool, open the one of the latest analysis
  const kind = pickedKind ?? list[0]?.config.kind ?? "topology";

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
            setSelections({ topology: NO_SELECTION, zigzag: NO_SELECTION });
          }}
          data={finished.map((run) => ({
            value: run.id,
            label: `Run ${run.index + 1} · seed ${run.seed}`,
          }))}
        />
        <Input.Wrapper label="Tool">
          {/* block-level, so it sits under its label like the inputs beside it */}
          <SegmentedControl
            display="flex"
            value={kind}
            onChange={(value) => setPickedKind(value as Kind)}
            data={KINDS.map((k) => {
              const count = byKind(k).length;
              return {
                value: k,
                label:
                  count > 0 ? `${ANALYSIS_KIND_LABELS[k]} (${count})` : ANALYSIS_KIND_LABELS[k],
              };
            })}
          />
        </Input.Wrapper>
      </Group>

      {runId && (
        <AnalysisWorkspace
          kind={kind}
          experiment={experiment}
          runId={runId}
          finishedRuns={finished.length}
          analyses={byKind(kind)}
          isPending={analyses.isPending}
          selection={selections[kind]}
          onSelect={(selection) => setSelections((current) => ({ ...current, [kind]: selection }))}
        />
      )}
    </Stack>
  );
}
