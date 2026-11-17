import {
  Alert,
  Anchor,
  Badge,
  Card,
  Code,
  Container,
  Group,
  Progress,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconClock,
  IconHeartbeat,
  IconHeartBroken,
  IconHelpCircle,
  IconLoader2,
  IconPlayerPause,
  IconPlugConnectedX,
  IconShieldCheck,
  IconZzz,
} from "@tabler/icons-react";
import type { ComponentType, ReactNode } from "react";
import { Link } from "react-router";

import { useActivity } from "../../api/queries";
import type {
  Activity,
  ActivityWorker,
  FailedJob,
  JobSubject,
  LeaseHealth,
  Recovery,
  RunningJob,
  WaitingGroup,
} from "../../api/types";
import { QueryState } from "../../components/QueryState";
import {
  activityTotals,
  describeRuns,
  formatAgo,
  formatSpan,
  isLost,
  jobProgress,
  positionLabel,
  secondsSince,
  shortWorkerName,
  subjectDetail,
  subjectLabel,
  subjectLink,
  watchdogHealth,
  workerState,
  type WatchdogHealth,
} from "../../lib/activityModel";
import { ANALYSIS_KIND_LABELS } from "../../lib/analysisModel";
import { formatDateTime, formatInteger } from "../../lib/format";

type Icon = ComponentType<{ size?: number }>;

interface BadgeStyle {
  color: string;
  label: string;
  Icon: Icon;
  hint: string;
}

const LEASE: Record<LeaseHealth, BadgeStyle> = {
  healthy: {
    color: "green",
    label: "Healthy",
    Icon: IconHeartbeat,
    hint: "The worker renews its lease on schedule.",
  },
  late: {
    color: "yellow",
    label: "Late",
    Icon: IconAlertTriangle,
    hint: "Heartbeats are overdue: the worker or the database may be overloaded.",
  },
  expired: {
    color: "red",
    label: "Expired",
    Icon: IconHeartBroken,
    hint: "The worker is presumed lost: the watchdog will retry the job elsewhere.",
  },
};

const WORKER_STATES: Record<string, BadgeStyle> = {
  busy: { color: "blue", label: "Busy", Icon: IconLoader2, hint: "Executing a job." },
  lost: {
    color: "red",
    label: "Unresponsive",
    Icon: IconHeartBroken,
    hint:
      "Its job went to a new attempt after its lease expired: the worker is presumed lost. " +
      "The queue forgets it once its heartbeat expires (about 90 s).",
  },
  idle: { color: "gray", label: "Idle", Icon: IconZzz, hint: "Waiting for a job." },
  suspended: {
    color: "yellow",
    label: "Suspended",
    Icon: IconPlayerPause,
    hint: "Takes no new job until it is resumed.",
  },
  started: { color: "gray", label: "Starting", Icon: IconClock, hint: "Starting up." },
  starting: { color: "gray", label: "Starting", Icon: IconClock, hint: "Starting up." },
  unknown: {
    color: "gray",
    label: "Unknown",
    Icon: IconHelpCircle,
    hint:
      "The queue lost this worker's registration (e.g. while the host was suspended) and " +
      "only keeps its heartbeat. It still takes jobs; its state shows again after the next one, " +
      "its host and counters after a restart.",
  },
};

const WATCHDOG: Record<WatchdogHealth, BadgeStyle> = {
  ok: { color: "green", label: "Sweeping", Icon: IconShieldCheck, hint: "Sweeping on schedule." },
  stale: {
    color: "red",
    label: "Stalled",
    Icon: IconAlertTriangle,
    hint: "Missed three sweeps: jobs of lost workers are not being recovered.",
  },
  absent: {
    color: "yellow",
    label: "Not reporting",
    Icon: IconHelpCircle,
    hint: "No sweep reported since the queue started.",
  },
  unknown: {
    color: "gray",
    label: "Unknown",
    Icon: IconPlugConnectedX,
    hint: "The queue is unreachable.",
  },
};

const JOB_NOTES: Record<string, string> = {
  claiming: "taking it from the queue",
  ended: "the job is over: wrapping up",
  superseded: "handed to a new attempt since",
};

const RECOVERY_LABELS: Record<string, string> = {
  retried: "Retried",
  failed: "Gave up",
  reenqueued: "Re-enqueued",
};

/** Status is always conveyed by icon + label, never by colour alone. */
function StyledBadge({ style }: { style: BadgeStyle }) {
  const { color, label, Icon, hint } = style;
  return (
    <Tooltip label={hint} multiline maw={320}>
      <Badge color={color} variant="light" leftSection={<Icon size={12} />} miw="max-content">
        {label}
      </Badge>
    </Tooltip>
  );
}

function Panel({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <Card withBorder padding="md">
      <Title order={5}>{title}</Title>
      <Text size="xs" c="dimmed" mb="sm" maw={720}>
        {description}
      </Text>
      {children}
    </Card>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return (
    <Text size="sm" c="dimmed" py="xs">
      {children}
    </Text>
  );
}

function Stat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <Card withBorder padding="md">
      <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
        {label}
      </Text>
      <Text fz={28} fw={700} className="tabular" lh={1.3}>
        {value}
      </Text>
      <Text size="xs" c="dimmed">
        {detail}
      </Text>
    </Card>
  );
}

/** Experiment (linked to the tab with the job's results), then what the job works on. */
function SubjectCell({ subject, label }: { subject: JobSubject; label?: string }) {
  const detail = subjectDetail(subject);
  return (
    <div>
      <Anchor component={Link} to={subjectLink(subject)} size="sm" fw={500}>
        {subject.experiment_name}
      </Anchor>
      <Text size="xs">{label ?? subjectLabel(subject)}</Text>
      {detail && (
        <Text size="xs" c="dimmed" lineClamp={1} title={detail} maw={360}>
          {detail}
        </Text>
      )}
    </div>
  );
}

function Moment({ iso, now }: { iso: string | null | undefined; now: string }) {
  return (
    <Text size="sm" className="tabular" title={iso ? formatDateTime(iso) : undefined}>
      {formatAgo(iso, now)}
    </Text>
  );
}

function Attempt({ attempt, max }: { attempt: number; max: number }) {
  return (
    <Text size="sm" className="tabular" c={attempt > 1 ? "yellow" : undefined}>
      {attempt} of {max}
    </Text>
  );
}

function RunningTable({ activity }: { activity: Activity }) {
  if (activity.running.length === 0) return <Empty>Nothing is running.</Empty>;
  const now = activity.at;
  return (
    <Table.ScrollContainer minWidth={900}>
      <Table verticalSpacing="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Job</Table.Th>
            <Table.Th>Progress</Table.Th>
            <Table.Th>Attempt</Table.Th>
            <Table.Th>Running for</Table.Th>
            <Table.Th>Lease</Table.Th>
            <Table.Th>Worker</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {activity.running.map((job: RunningJob) => {
            const progress = jobProgress(job);
            const elapsed = secondsSince(job.started_at, now);
            return (
              <Table.Tr key={`${job.kind}-${job.id}`}>
                <Table.Td>
                  <SubjectCell subject={job.subject} />
                </Table.Td>
                <Table.Td miw={180}>
                  <Text size="sm" className="tabular">
                    {progress.label}
                  </Text>
                  <Progress
                    size="xs"
                    value={progress.percent ?? 100}
                    animated={progress.percent === null}
                    striped={progress.percent === null}
                    aria-label={progress.label}
                  />
                </Table.Td>
                <Table.Td>
                  <Attempt attempt={job.attempt} max={activity.limits.max_attempts} />
                </Table.Td>
                <Table.Td>
                  <Text
                    size="sm"
                    className="tabular"
                    title={job.started_at ? formatDateTime(job.started_at) : undefined}
                  >
                    {elapsed === null ? "—" : formatSpan(elapsed)}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <StyledBadge style={LEASE[job.lease]} />
                  <Text size="xs" c="dimmed" mt={4} className="tabular">
                    beat {formatAgo(job.heartbeat_at, now)}
                  </Text>
                </Table.Td>
                <Table.Td>
                  {job.worker ? (
                    <Code>{shortWorkerName(job.worker)}</Code>
                  ) : (
                    <Tooltip label="No worker reports holding this attempt of the job.">
                      <Text size="sm" c="dimmed">
                        none
                      </Text>
                    </Tooltip>
                  )}
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

/** "Runs 3–5", or "Zigzag across generations · runs 1–30". */
function waitingLabel(group: WaitingGroup): string {
  const runs = describeRuns(group.run_indices);
  if (!group.analysis) return runs.charAt(0).toUpperCase() + runs.slice(1);
  return `${ANALYSIS_KIND_LABELS[group.analysis.kind]} · ${runs}`;
}

function WaitingTable({ activity }: { activity: Activity }) {
  if (activity.waiting.length === 0) return <Empty>No job is waiting.</Empty>;
  const grace = formatSpan(activity.limits.enqueue_grace_seconds);
  return (
    <Table.ScrollContainer minWidth={760}>
      <Table verticalSpacing="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Next</Table.Th>
            <Table.Th>Jobs</Table.Th>
            <Table.Th>Waiting since</Table.Th>
            <Table.Th>Notes</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {activity.waiting.map((group) => (
            <Table.Tr key={`${group.kind}-${group.batch_id ?? group.experiment_id}`}>
              <Table.Td>
                <Text size="sm" className="tabular" fw={group.next_position === 1 ? 600 : 400}>
                  {positionLabel(group.next_position)}
                </Text>
              </Table.Td>
              <Table.Td>
                <SubjectCell
                  subject={{ ...group, run_id: "", run_index: 0 }}
                  label={waitingLabel(group)}
                />
              </Table.Td>
              <Table.Td>
                <Moment iso={group.enqueued_at} now={activity.at} />
              </Table.Td>
              <Table.Td>
                <Stack gap={4}>
                  {group.retries > 0 && (
                    <Text size="xs" c="yellow">
                      {group.retries} retried after a lost worker
                    </Text>
                  )}
                  {(group.missing ?? 0) > 0 && (
                    <Text size="xs" c="yellow">
                      {group.missing} not in the queue: the watchdog enqueues them again after{" "}
                      {grace}
                    </Text>
                  )}
                </Stack>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

function WorkersTable({ activity }: { activity: Activity }) {
  if (activity.workers.length === 0) {
    return (
      <Empty>
        No worker is registered with the queue. Start some with{" "}
        <Code>docker compose up -d --scale worker=4</Code>.
      </Empty>
    );
  }
  const now = activity.at;
  return (
    <Table.ScrollContainer minWidth={900}>
      <Table verticalSpacing="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>Worker</Table.Th>
            <Table.Th>State</Table.Th>
            <Table.Th>Job</Table.Th>
            <Table.Th>Host · PID</Table.Th>
            <Table.Th>Up for</Table.Th>
            <Table.Th>Last seen</Table.Th>
            <Table.Th ta="right">Jobs done</Table.Th>
            <Table.Th ta="right">Crashed</Table.Th>
            <Table.Th ta="right">Busy for</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {activity.workers.map((worker: ActivityWorker) => {
            const state = workerState(worker);
            const note = worker.job_status ? JOB_NOTES[worker.job_status] : undefined;
            const up = secondsSince(worker.born_at, now);
            return (
              <Table.Tr key={worker.name}>
                <Table.Td>
                  <Code title={worker.name}>{shortWorkerName(worker.name)}</Code>
                </Table.Td>
                <Table.Td>
                  <StyledBadge
                    style={
                      WORKER_STATES[state] ?? {
                        color: "gray",
                        label: state,
                        Icon: IconHelpCircle,
                        hint: "State reported by the queue.",
                      }
                    }
                  />
                </Table.Td>
                <Table.Td>
                  {worker.subject ? (
                    <SubjectCell subject={worker.subject} />
                  ) : (
                    <Text size="sm" c="dimmed">
                      {worker.job ? `deleted ${worker.job.kind}` : "—"}
                    </Text>
                  )}
                  {note && (
                    <Text size="xs" c={isLost(worker) ? "red" : "dimmed"}>
                      attempt {worker.job?.attempt}: {note}
                    </Text>
                  )}
                </Table.Td>
                <Table.Td>
                  <Text size="sm" className="tabular">
                    {worker.hostname ?? "—"}
                    {worker.pid !== null && ` · ${worker.pid}`}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Text size="sm" className="tabular">
                    {up === null ? "—" : formatSpan(up)}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Moment iso={worker.seen_at} now={now} />
                </Table.Td>
                <Table.Td ta="right" className="tabular">
                  {formatInteger(worker.successful_jobs)}
                </Table.Td>
                <Table.Td ta="right" className="tabular">
                  {formatInteger(worker.failed_jobs)}
                </Table.Td>
                <Table.Td ta="right" className="tabular">
                  {formatSpan(worker.working_seconds)}
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

function QueueCounts({ activity }: { activity: Activity }) {
  const queue = activity.queue;
  if (!queue) return <Empty>The queue is unreachable.</Empty>;
  const rows: [string, number, string][] = [
    ["Waiting", queue.waiting, "Jobs waiting for a worker."],
    ["Started", queue.started, "Jobs held by a worker."],
    ["Finished", queue.finished, "Jobs finished in the last hour."],
    [
      "Crashed",
      queue.failed,
      "Jobs that killed their worker process (kept a week); errors raised by a run or an " +
        "analysis are recorded on the job instead.",
    ],
    ["Deferred", queue.deferred, "Jobs waiting for another job."],
    ["Scheduled", queue.scheduled, "Jobs waiting for a time."],
  ];
  return (
    <SimpleGrid cols={{ base: 2, xs: 3 }} spacing="xs">
      {rows.map(([label, value, hint]) => (
        <Tooltip key={label} label={hint} multiline maw={300}>
          <div>
            <Text size="xs" c="dimmed">
              {label}
            </Text>
            <Text fw={600} className="tabular">
              {formatInteger(value)}
            </Text>
          </div>
        </Tooltip>
      ))}
    </SimpleGrid>
  );
}

function RecoveryRow({ recovery, now }: { recovery: Recovery; now: string }) {
  const { subject, job } = recovery;
  return (
    <Table.Tr>
      <Table.Td>
        <Moment iso={recovery.at} now={now} />
      </Table.Td>
      <Table.Td>
        {subject ? (
          <SubjectCell subject={subject} />
        ) : (
          <Text size="sm" c="dimmed">
            deleted {job.kind}
          </Text>
        )}
      </Table.Td>
      <Table.Td>
        <Text size="sm" c={recovery.action === "failed" ? "red" : undefined}>
          {RECOVERY_LABELS[recovery.action] ?? recovery.action}
        </Text>
        <Text size="xs" c="dimmed">
          attempt {job.attempt}
        </Text>
      </Table.Td>
    </Table.Tr>
  );
}

function WatchdogPanel({ activity }: { activity: Activity }) {
  const health = watchdogHealth(activity);
  const watchdog = activity.watchdog;
  return (
    <Stack gap="sm">
      <Group gap="sm">
        <StyledBadge style={WATCHDOG[health]} />
        {watchdog && (
          <Text size="sm" c="dimmed">
            last sweep {formatAgo(watchdog.swept_at, activity.at)} · every{" "}
            {formatSpan(watchdog.interval_seconds)}
          </Text>
        )}
      </Group>
      {watchdog && watchdog.recoveries.length === 0 && (
        <Empty>No job needed recovering since the queue started.</Empty>
      )}
      {watchdog && watchdog.recoveries.length > 0 && (
        <Table.ScrollContainer minWidth={420} maxHeight={360}>
          <Table verticalSpacing={6}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>When</Table.Th>
                <Table.Th>Job</Table.Th>
                <Table.Th>Action</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {watchdog.recoveries.map((recovery, i) => (
                <RecoveryRow key={i} recovery={recovery} now={activity.at} />
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
    </Stack>
  );
}

function FailuresTable({ activity }: { activity: Activity }) {
  if (activity.failures.length === 0) return <Empty>No job has failed.</Empty>;
  return (
    <Table.ScrollContainer minWidth={900}>
      <Table verticalSpacing="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>When</Table.Th>
            <Table.Th>Job</Table.Th>
            <Table.Th>Attempt</Table.Th>
            <Table.Th>Error</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {activity.failures.map((job: FailedJob) => (
            <Table.Tr key={`${job.kind}-${job.id}`}>
              <Table.Td>
                <Moment iso={job.finished_at} now={activity.at} />
              </Table.Td>
              <Table.Td>
                <SubjectCell subject={job.subject} />
              </Table.Td>
              <Table.Td>
                <Attempt attempt={job.attempt} max={activity.limits.max_attempts} />
              </Table.Td>
              <Table.Td>
                <Text
                  size="xs"
                  ff="monospace"
                  lineClamp={3}
                  title={job.error ?? undefined}
                  maw={520}
                >
                  {job.error ?? "—"}
                </Text>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  );
}

function Alerts({ activity, stale }: { activity: Activity; stale: boolean }) {
  const totals = activityTotals(activity);
  const health = watchdogHealth(activity);
  return (
    <>
      {stale && (
        <Alert color="red" icon={<IconPlugConnectedX size={16} />} title="API unreachable">
          Showing the state at {formatDateTime(activity.at)}; retrying every 2 s.
        </Alert>
      )}
      {activity.queue_error && (
        <Alert color="red" icon={<IconPlugConnectedX size={16} />} title="Job queue unreachable">
          Workers cannot take new jobs; only what the database knows is shown.{" "}
          <Code>{activity.queue_error}</Code>
        </Alert>
      )}
      {activity.queue && totals.workers === 0 && totals.waiting > 0 && (
        <Alert color="yellow" icon={<IconAlertTriangle size={16} />} title="No worker is running">
          {formatInteger(totals.waiting)} job(s) wait for a worker. Start some with{" "}
          <Code>docker compose up -d --scale worker=4</Code>.
        </Alert>
      )}
      {(health === "stale" || health === "absent") && (
        <Alert color="yellow" icon={<IconAlertTriangle size={16} />} title="Watchdog silent">
          {WATCHDOG[health].hint} Jobs of lost workers stay running and lost queue entries are not
          restored until it sweeps again (<Code>docker compose up -d watchdog</Code>).
        </Alert>
      )}
    </>
  );
}

function ActivityView({ activity, stale }: { activity: Activity; stale: boolean }) {
  const totals = activityTotals(activity);
  const analyses = totals.running - totals.runningRuns;
  return (
    <Stack gap="lg">
      <Alerts activity={activity} stale={stale} />
      <SimpleGrid cols={{ base: 2, sm: 4 }}>
        <Stat
          label="Workers busy"
          value={`${totals.busy} / ${totals.workers}`}
          detail={`${totals.workers - totals.busy - totals.lost} idle${
            totals.lost > 0 ? ` · ${totals.lost} unresponsive` : ""
          }`}
        />
        <Stat
          label="Running"
          value={formatInteger(totals.running)}
          detail={`${totals.runningRuns} run(s) · ${analyses} analysis(es)${
            totals.expired > 0 ? ` · ${totals.expired} lost` : ""
          }`}
        />
        <Stat
          label="Waiting"
          value={formatInteger(totals.waiting)}
          detail={
            totals.missing > 0
              ? `${formatInteger(totals.missing)} not in the queue`
              : `${activity.waiting.length} group(s)`
          }
        />
        <Stat
          label="Last 24 hours"
          value={formatInteger(totals.completed)}
          detail={`completed · ${totals.failed} failed · ${totals.cancelled} cancelled`}
        />
      </SimpleGrid>
      <Panel
        title="Running"
        description="Runs and analyses being executed, oldest first. A worker renews the lease of its job every few seconds; once it expires the watchdog hands the job to another worker."
      >
        <RunningTable activity={activity} />
      </Panel>
      <Panel
        title="Waiting"
        description="Queued jobs, per experiment (runs) or per batch of analyses, in the order the workers will take them."
      >
        <WaitingTable activity={activity} />
      </Panel>
      <Panel
        title="Workers"
        description="Worker processes registered with the job queue. Each executes one job at a time."
      >
        <WorkersTable activity={activity} />
      </Panel>
      <SimpleGrid cols={{ base: 1, md: 2 }}>
        <Panel
          title={`Job queue${activity.queue ? ` · ${activity.queue.name}` : ""}`}
          description="Jobs in the queue (Redis) and in its registries."
        >
          <QueueCounts activity={activity} />
        </Panel>
        <Panel
          title="Watchdog"
          description="Retries the jobs of lost workers and restores jobs lost by the queue. Its last 50 recoveries:"
        >
          <WatchdogPanel activity={activity} />
        </Panel>
      </SimpleGrid>
      <Panel
        title="Recent failures"
        description="The 20 most recent runs and analyses that failed."
      >
        <FailuresTable activity={activity} />
      </Panel>
    </Stack>
  );
}

export function ActivityPage() {
  const { data, isPending, error, isRefetchError } = useActivity();
  return (
    <Container size="xl">
      <Group justify="space-between" mb="md" align="flex-end">
        <div>
          <Title order={2}>Activity</Title>
          <Text size="sm" c="dimmed">
            Workers, the job queue and what they are working on, refreshed every 2 s.
          </Text>
        </div>
        {data && (
          <Badge variant="dot" color={isRefetchError ? "red" : "green"}>
            {isRefetchError ? "Offline" : "Live"} · {new Date(data.at).toLocaleTimeString()}
          </Badge>
        )}
      </Group>
      <QueryState isPending={isPending} error={data ? null : error}>
        {data && <ActivityView activity={data} stale={isRefetchError} />}
      </QueryState>
    </Container>
  );
}
