import { describe, expect, it } from "vitest";

import type { Activity, ActivityWorker, JobSubject, RunningJob } from "../api/types";
import {
  activityTotals,
  describeRuns,
  formatAgo,
  formatSpan,
  jobProgress,
  positionLabel,
  secondsSince,
  shortWorkerName,
  subjectDetail,
  subjectLabel,
  subjectLink,
  watchdogHealth,
  workerState,
} from "./activityModel";

const NOW = "2026-11-17T12:00:00Z";

const run: JobSubject = {
  experiment_id: "e1",
  experiment_name: "DTLZ2",
  run_id: "r1",
  run_index: 2,
  analysis: null,
  batch_id: null,
};

const analysis: JobSubject = {
  ...run,
  analysis: {
    kind: "zigzag",
    epsilons: [0.1],
    max_dimension: 0,
    normalization: "none",
    middle: "union",
    representatives: 10,
  },
  batch_id: "b1",
};

function job(overrides: Partial<RunningJob>): RunningJob {
  return {
    kind: "run",
    id: "j",
    subject: run,
    attempt: 1,
    done: 0,
    total: 0,
    started_at: null,
    heartbeat_at: null,
    lease: "healthy",
    worker: null,
    ...overrides,
  };
}

function worker(overrides: Partial<ActivityWorker>): ActivityWorker {
  return {
    name: "w",
    state: "idle",
    hostname: null,
    pid: null,
    job: null,
    job_status: null,
    subject: null,
    born_at: null,
    seen_at: null,
    successful_jobs: 0,
    failed_jobs: 0,
    working_seconds: 0,
    ...overrides,
  };
}

function activity(overrides: Partial<Activity>): Activity {
  return {
    at: NOW,
    limits: {
      heartbeat_interval_seconds: 5,
      lease_timeout_seconds: 60,
      max_attempts: 3,
      enqueue_grace_seconds: 120,
    },
    queue: {
      name: "esphea-runs",
      waiting: 0,
      started: 0,
      failed: 0,
      finished: 0,
      deferred: 0,
      scheduled: 0,
    },
    queue_error: null,
    workers: [],
    watchdog: null,
    running: [],
    waiting: [],
    failures: [],
    finished: [],
    ...overrides,
  };
}

describe("ages", () => {
  it("are measured against the server time and never negative", () => {
    expect(secondsSince("2026-11-17T11:59:30Z", NOW)).toBe(30);
    expect(secondsSince("2026-11-17T12:00:05Z", NOW)).toBe(0);
    expect(secondsSince(null, NOW)).toBeNull();
  });

  it("read as spans up to days", () => {
    expect(formatSpan(4.25)).toBe("4.3 s");
    expect(formatSpan(9.97)).toBe("10 s");
    expect(formatSpan(59.7)).toBe("1 min 0 s");
    expect(formatSpan(179.6)).toBe("3 min 0 s");
    expect(formatSpan(3 * 86_400 + 5 * 3600)).toBe("3 d 5 h");
    expect(formatAgo("2026-11-17T11:58:00Z", NOW)).toBe("2 min 0 s ago");
    expect(formatAgo(NOW, NOW)).toBe("just now");
    expect(formatAgo(null, NOW)).toBe("—");
  });
});

describe("describeRuns", () => {
  it("collapses consecutive runs, 1-based", () => {
    expect(describeRuns([4])).toBe("run 5");
    expect(describeRuns([0, 1, 2, 6, 8, 9])).toBe("runs 1–3, 7, 9–10");
    expect(describeRuns([0, 0, 1])).toBe("runs 1–2");
  });

  it("counts runs too scattered to list", () => {
    expect(describeRuns([0, 2, 4, 6, 8])).toBe("5 runs");
    expect(describeRuns([])).toBe("");
  });
});

describe("subjects", () => {
  it("name the run and the analysis", () => {
    expect(subjectLabel(run)).toBe("Run 3");
    expect(subjectLabel(analysis)).toBe("Run 3 · Zigzag across generations");
    expect(subjectDetail(run)).toBeNull();
    expect(subjectDetail(analysis)).toContain("zigzag · ε 0.1");
  });

  it("link to the tab that shows their results", () => {
    expect(subjectLink(run)).toBe("/experiments/e1?tab=runs");
    expect(subjectLink(analysis)).toBe("/experiments/e1?tab=topology");
  });
});

describe("jobProgress", () => {
  it("counts generations of runs and steps of analyses", () => {
    expect(jobProgress(job({ done: 25, total: 100 }))).toEqual({
      percent: 25,
      label: "generation 25 / 100",
    });
    expect(jobProgress(job({ kind: "analysis", done: 3, total: 4 })).label).toBe("step 3 / 4");
  });

  it("is indeterminate before an analysis counted its steps", () => {
    expect(jobProgress(job({ kind: "analysis" }))).toEqual({
      percent: null,
      label: "counting steps…",
    });
  });
});

describe("labels", () => {
  it("tell the place in the queue", () => {
    expect([0, 1, 2, 1500, null].map(positionLabel)).toEqual([
      "being taken",
      "next",
      "#2",
      "#1,500",
      "—",
    ]);
  });

  it("shorten RQ worker names only", () => {
    expect(shortWorkerName("0ce40b6319cb40d0b3ed162b9f56e0f2")).toBe("0ce40b63");
    expect(shortWorkerName("gpu-worker")).toBe("gpu-worker");
  });
});

describe("watchdogHealth", () => {
  const swept = (at: string) => ({ swept_at: at, interval_seconds: 10, recoveries: [] });

  it("is ok within three sweeps and stale after", () => {
    expect(watchdogHealth(activity({ watchdog: swept("2026-11-17T11:59:31Z") }))).toBe("ok");
    expect(watchdogHealth(activity({ watchdog: swept("2026-11-17T11:59:29Z") }))).toBe("stale");
  });

  it("is absent without a report and unknown without the queue", () => {
    expect(watchdogHealth(activity({}))).toBe("absent");
    expect(watchdogHealth(activity({ queue: null, queue_error: "down" }))).toBe("unknown");
  });
});

const ref = { kind: "run" as const, id: "j", attempt: 1 };

describe("workerState", () => {
  it("trusts the database over the queue about the job a worker holds", () => {
    expect(workerState(worker({ state: "busy", job: ref, job_status: "running" }))).toBe("busy");
    expect(workerState(worker({ state: "idle", job: ref, job_status: "claiming" }))).toBe("busy");
    expect(workerState(worker({ state: "busy", job: ref, job_status: "superseded" }))).toBe("lost");
    expect(workerState(worker({ state: "unknown" }))).toBe("unknown");
  });
});

describe("activityTotals", () => {
  it("adds up workers, jobs and the last day", () => {
    const totals = activityTotals(
      activity({
        workers: [
          worker({ name: "a", job: ref, job_status: "running" }),
          worker({ name: "b", state: "busy" }),
          worker({ name: "c" }),
          worker({ name: "d", state: "busy", job: ref, job_status: "superseded" }),
        ],
        running: [job({}), job({ kind: "analysis", lease: "expired" })],
        waiting: [
          {
            kind: "run",
            experiment_id: "e1",
            experiment_name: "DTLZ2",
            analysis: null,
            batch_id: null,
            run_indices: [0, 1, 2],
            retries: 1,
            next_position: 1,
            missing: 2,
            enqueued_at: NOW,
          },
        ],
        finished: [
          { kind: "run", completed: 4, failed: 1, cancelled: 0 },
          { kind: "analysis", completed: 2, failed: 0, cancelled: 3 },
        ],
      }),
    );
    expect(totals).toEqual({
      workers: 4,
      busy: 2,
      lost: 1,
      running: 2,
      runningRuns: 1,
      expired: 1,
      waiting: 3,
      missing: 2,
      retries: 1,
      completed: 6,
      failed: 1,
      cancelled: 3,
    });
  });
});
