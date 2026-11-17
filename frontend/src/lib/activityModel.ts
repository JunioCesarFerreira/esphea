/** Pure helpers of the Activity page: ages, labels and health of jobs, workers and watchdog. */
import type { Activity, ActivityWorker, JobSubject, RunningJob } from "../api/types";
import { ANALYSIS_KIND_LABELS, describeConfig } from "./analysisModel";
import { formatDuration, formatInteger } from "./format";

/** Seconds from ``iso`` to the server time ``now`` (never negative; null without a time). */
export function secondsSince(iso: string | null | undefined, now: string): number | null {
  if (!iso) return null;
  return Math.max(0, (Date.parse(now) - Date.parse(iso)) / 1000);
}

/** "3.2 s", "5 min 3 s", "2 h 4 min", "3 d 4 h". */
export function formatSpan(seconds: number): string {
  if (seconds < 86_400) return formatDuration(seconds);
  return `${Math.floor(seconds / 86_400)} d ${Math.floor((seconds % 86_400) / 3600)} h`;
}

export function formatAgo(iso: string | null | undefined, now: string): string {
  const seconds = secondsSince(iso, now);
  if (seconds === null) return "—";
  return seconds < 1 ? "just now" : `${formatSpan(seconds)} ago`;
}

/** 1-based run numbers, with consecutive ones collapsed: "runs 1–3, 7"; "40 runs" if scattered. */
export function describeRuns(indices: readonly number[]): string {
  const runs = [...new Set(indices)].sort((a, b) => a - b);
  if (runs.length === 0) return "";
  const ranges: string[] = [];
  let start = runs[0] ?? 0;
  let previous = start;
  for (const run of [...runs.slice(1), Number.NaN]) {
    if (run === previous + 1) {
      previous = run;
      continue;
    }
    ranges.push(start === previous ? `${start + 1}` : `${start + 1}–${previous + 1}`);
    start = run;
    previous = run;
  }
  if (ranges.length > 4) return `${runs.length} runs`;
  return `${runs.length === 1 ? "run" : "runs"} ${ranges.join(", ")}`;
}

/** "Run 3" or "Run 3 · Zigzag across generations". */
export function subjectLabel(subject: JobSubject): string {
  const run = `Run ${subject.run_index + 1}`;
  return subject.analysis ? `${run} · ${ANALYSIS_KIND_LABELS[subject.analysis.kind]}` : run;
}

/** Settings of an analysis (null for a run). */
export function subjectDetail(subject: Pick<JobSubject, "analysis">): string | null {
  return subject.analysis ? describeConfig(subject.analysis) : null;
}

/** The experiment tab where the job's results appear. */
export function subjectLink(subject: Pick<JobSubject, "experiment_id" | "analysis">): string {
  return `/experiments/${subject.experiment_id}?tab=${subject.analysis ? "topology" : "runs"}`;
}

export function jobProgress(job: RunningJob): { percent: number | null; label: string } {
  if (job.total <= 0) return { percent: null, label: "counting steps…" };
  const unit = job.kind === "run" ? "generation" : "step";
  return {
    percent: Math.min(100, (100 * job.done) / job.total),
    label: `${unit} ${formatInteger(job.done)} / ${formatInteger(job.total)}`,
  };
}

/** "next", "#5", "being taken" (a worker is claiming it) or "—" (not in the queue). */
export function positionLabel(position: number | null): string {
  if (position === null) return "—";
  if (position === 0) return "being taken";
  return position === 1 ? "next" : `#${formatInteger(position)}`;
}

/** RQ names workers with 32 hex digits; the first 8 tell them apart. */
export function shortWorkerName(name: string): string {
  return /^[0-9a-f]{32}$/.test(name) ? name.slice(0, 8) : name;
}

export type WatchdogHealth = "ok" | "stale" | "absent" | "unknown";

/** ``unknown`` when the queue (Redis) is unreachable; ``stale`` after three missed sweeps. */
export function watchdogHealth(activity: Activity): WatchdogHealth {
  if (!activity.queue) return "unknown";
  const watchdog = activity.watchdog;
  if (!watchdog) return "absent";
  const age = secondsSince(watchdog.swept_at, activity.at) ?? Number.POSITIVE_INFINITY;
  return age <= 3 * watchdog.interval_seconds ? "ok" : "stale";
}

/** A worker whose job went to a new attempt after its lease expired: presumed lost. */
export function isLost(worker: ActivityWorker): boolean {
  return worker.job_status === "superseded";
}

export function isBusy(worker: ActivityWorker): boolean {
  if (worker.job_status === null) return worker.state === "busy";
  return !isLost(worker);
}

/** State shown for a worker: the queue's, corrected by what the database knows. */
export function workerState(worker: ActivityWorker): string {
  if (isLost(worker)) return "lost";
  return isBusy(worker) ? "busy" : worker.state;
}

export interface ActivityTotals {
  workers: number;
  busy: number;
  lost: number;
  running: number;
  runningRuns: number;
  expired: number;
  waiting: number;
  missing: number;
  retries: number;
  completed: number;
  failed: number;
  cancelled: number;
}

export function activityTotals(activity: Activity): ActivityTotals {
  const sum = <T>(items: readonly T[], value: (item: T) => number) =>
    items.reduce((total, item) => total + value(item), 0);
  return {
    workers: activity.workers.length,
    busy: activity.workers.filter(isBusy).length,
    lost: activity.workers.filter(isLost).length,
    running: activity.running.length,
    runningRuns: activity.running.filter((job) => job.kind === "run").length,
    expired: activity.running.filter((job) => job.lease === "expired").length,
    waiting: sum(activity.waiting, (group) => group.run_indices.length),
    missing: sum(activity.waiting, (group) => group.missing ?? 0),
    retries: sum(activity.waiting, (group) => group.retries),
    completed: sum(activity.finished, (row) => row.completed),
    failed: sum(activity.finished, (row) => row.failed),
    cancelled: sum(activity.finished, (row) => row.cancelled),
  };
}
