import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from esphea.experiments.config import ExperimentConfig, NSGA2Config
from esphea.messaging.ports import (
    JobKind,
    JobRef,
    QueueState,
    RecoveryRecord,
    WatchdogState,
    WorkerState,
)
from esphea.messaging.redis import _job_id, parse_job_id
from esphea.persistence.models import AnalysisRow, RunRow, RunStatus
from esphea.persistence.repositories import AnalysisRepository, ExperimentRepository
from esphea.services.activity import (
    ActivityLimits,
    ActivityService,
    LeaseHealth,
    WorkerJobStatus,
)
from esphea.topology.config import ZigzagAnalysisConfig
from tests.integration.conftest import FakeMonitor

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
LIMITS = ActivityLimits(
    heartbeat_interval=timedelta(seconds=5),
    lease_timeout=timedelta(seconds=60),
    max_attempts=3,
    enqueue_grace=timedelta(seconds=120),
)
ZIGZAG = ZigzagAnalysisConfig(epsilons=(0.1,)).model_dump(mode="json", exclude={"kind"})


def add_experiment(
    sessions: sessionmaker[Session], n_runs: int, name: str = "e"
) -> list[uuid.UUID]:
    config = ExperimentConfig(
        name=name, algorithm=NSGA2Config(pop_size=12), n_gen=50, n_runs=n_runs
    )
    with sessions.begin() as session:
        return [run.id for run in ExperimentRepository(session).add(config).runs]


def add_analysis(
    sessions: sessionmaker[Session], run_id: uuid.UUID, batch_id: uuid.UUID | None = None
) -> uuid.UUID:
    with sessions.begin() as session:
        return AnalysisRepository(session).add(run_id, "zigzag", ZIGZAG, batch_id=batch_id).id


def set_run(sessions: sessionmaker[Session], run_id: uuid.UUID, **values: Any) -> None:
    with sessions.begin() as session:
        session.execute(update(RunRow).where(RunRow.id == run_id).values(**values))


def set_analysis(sessions: sessionmaker[Session], analysis_id: uuid.UUID, **values: Any) -> None:
    with sessions.begin() as session:
        session.execute(update(AnalysisRow).where(AnalysisRow.id == analysis_id).values(**values))


def running(sessions: sessionmaker[Session], run_id: uuid.UUID, attempt: int, beat: float) -> None:
    """Claimed by ``attempt`` a minute ago; last heartbeat ``beat`` seconds ago."""
    set_run(
        sessions,
        run_id,
        status=RunStatus.RUNNING,
        attempt=attempt,
        generation=7,
        started_at=NOW - timedelta(minutes=1, seconds=attempt),
        heartbeat_at=NOW - timedelta(seconds=beat),
    )


def worker(name: str, job: JobRef | None) -> WorkerState:
    return WorkerState(
        name=name,
        state="busy" if job else "idle",
        hostname="host",
        pid=7,
        job=job,
        born_at=NOW - timedelta(hours=1),
        seen_at=NOW,
        successful_jobs=3,
        failed_jobs=0,
        working_seconds=120.0,
    )


def queue_state(waiting: tuple[JobRef, ...] = (), *workers: WorkerState) -> QueueState:
    return QueueState(
        name="esphea-runs",
        waiting=waiting,
        started=len([w for w in workers if w.job]),
        failed=0,
        finished=0,
        deferred=0,
        scheduled=0,
        workers=workers,
    )


@pytest.fixture
def service(sessions: sessionmaker[Session], monitor: FakeMonitor) -> ActivityService:
    return ActivityService(sessions(), monitor=monitor, limits=LIMITS, clock=lambda: NOW)


def test_job_ids_round_trip() -> None:
    ref = JobRef(JobKind.ANALYSIS, uuid.uuid4(), 2)
    assert parse_job_id(_job_id(ref)) == ref
    assert parse_job_id("some-other-job") is None
    assert parse_job_id("run-not-a-uuid-1") is None


def test_running_jobs_with_their_worker_and_lease(
    sessions: sessionmaker[Session], monitor: FakeMonitor, service: ActivityService
) -> None:
    healthy, late, expired = add_experiment(sessions, n_runs=3)
    running(sessions, healthy, attempt=1, beat=2)
    running(sessions, late, attempt=2, beat=30)
    running(sessions, expired, attempt=3, beat=90)
    monitor.state = queue_state((), worker("w1", JobRef(JobKind.RUN, healthy, 1)))

    activity = service.snapshot()

    assert [job.id for job in activity.running] == [expired, late, healthy]  # oldest first
    by_id = {job.id: job for job in activity.running}
    assert by_id[healthy].lease == LeaseHealth.HEALTHY
    assert by_id[late].lease == LeaseHealth.LATE
    assert by_id[expired].lease == LeaseHealth.EXPIRED
    assert by_id[healthy].worker == "w1"
    assert by_id[late].worker is None  # nobody holds attempt 2
    assert (by_id[healthy].done, by_id[healthy].total) == (7, 50)
    assert by_id[late].subject.run_index == 1
    assert by_id[late].heartbeat_at == NOW - timedelta(seconds=30)
    assert activity.waiting == []


def test_waiting_jobs_grouped_with_their_place_in_the_queue(
    sessions: sessionmaker[Session], monitor: FakeMonitor, service: ActivityService
) -> None:
    queued, taken, lost = add_experiment(sessions, n_runs=3, name="runs")
    set_run(sessions, lost, attempt=1, error="worker lost during attempt 1; retrying")
    [source] = add_experiment(sessions, n_runs=1, name="analyses")
    set_run(sessions, source, status=RunStatus.COMPLETED, finished_at=NOW)
    batch = uuid.uuid4()
    first, second = add_analysis(sessions, source, batch), add_analysis(sessions, source, batch)
    alone = add_analysis(sessions, source)
    set_analysis(sessions, alone, enqueued_at=NOW - timedelta(hours=1))
    monitor.state = queue_state(
        (
            JobRef(JobKind.ANALYSIS, second, 1),
            JobRef(JobKind.RUN, queued, 1),
            JobRef(JobKind.ANALYSIS, first, 1),
        ),
        worker("w1", JobRef(JobKind.RUN, taken, 1)),  # claiming it right now
    )

    groups = service.snapshot().waiting

    assert [(g.kind, g.batch_id, g.next_position) for g in groups] == [
        (JobKind.RUN, None, 0),
        (JobKind.ANALYSIS, batch, 1),
        (JobKind.ANALYSIS, None, None),  # missing from the queue: listed last
    ]
    runs, batch_group, single = groups
    assert (runs.experiment_name, runs.run_indices, runs.retries, runs.missing) == (
        "runs",
        (0, 1, 2),
        1,
        1,
    )
    assert (batch_group.run_indices, batch_group.missing) == ((0, 0), 0)
    assert batch_group.analysis == ZigzagAnalysisConfig(epsilons=(0.1,))
    assert (single.missing, single.enqueued_at) == (1, NOW - timedelta(hours=1))


def test_the_job_of_each_worker_is_checked_against_the_database(
    sessions: sessionmaker[Session], monitor: FakeMonitor, service: ActivityService
) -> None:
    executing, claimed, recovered, done = add_experiment(sessions, n_runs=4)
    running(sessions, executing, attempt=1, beat=1)
    # its worker was presumed lost: queued again, attempt 2 not started yet
    set_run(sessions, recovered, attempt=1, error="worker lost during attempt 1; retrying")
    set_run(sessions, done, status=RunStatus.COMPLETED, attempt=1, finished_at=NOW)
    monitor.state = queue_state(
        (),
        worker("a", JobRef(JobKind.RUN, executing, 1)),
        worker("b", JobRef(JobKind.RUN, claimed, 1)),
        worker("c", JobRef(JobKind.RUN, recovered, 1)),
        worker("d", JobRef(JobKind.RUN, done, 1)),
        worker("e", JobRef(JobKind.ANALYSIS, uuid.uuid4(), 1)),  # deleted since
        worker("f", None),
    )

    workers = service.snapshot().workers

    assert [(w.state.name, w.job_status) for w in workers] == [
        ("a", WorkerJobStatus.RUNNING),
        ("b", WorkerJobStatus.CLAIMING),
        ("c", WorkerJobStatus.SUPERSEDED),
        ("d", WorkerJobStatus.ENDED),
        ("e", WorkerJobStatus.ENDED),
        ("f", None),
    ]
    assert [w.subject.run_index if w.subject else None for w in workers] == [
        0,
        1,
        2,
        3,
        None,
        None,
    ]


def test_the_database_view_survives_an_unreachable_queue(
    sessions: sessionmaker[Session], monitor: FakeMonitor, service: ActivityService
) -> None:
    run_id, _ = add_experiment(sessions, n_runs=2)
    running(sessions, run_id, attempt=1, beat=1)
    monitor.error = ConnectionError("Redis is down")

    activity = service.snapshot()

    assert activity.queue is None
    assert activity.queue_error == "ConnectionError: Redis is down"
    assert activity.watchdog is None
    assert [(job.id, job.worker) for job in activity.running] == [(run_id, None)]
    [group] = activity.waiting
    assert (group.next_position, group.missing) == (None, None)


def test_recent_failures_and_finished_jobs(
    sessions: sessionmaker[Session], service: ActivityService
) -> None:
    old, recent, done, cancelled = add_experiment(sessions, n_runs=4)
    set_run(sessions, old, status=RunStatus.FAILED, finished_at=NOW - timedelta(days=2), error="a")
    set_run(sessions, recent, status=RunStatus.FAILED, finished_at=NOW, error="b", attempt=3)
    set_run(sessions, done, status=RunStatus.COMPLETED, finished_at=NOW - timedelta(hours=1))
    set_run(sessions, cancelled, status=RunStatus.CANCELLED, finished_at=NOW)
    analysis = add_analysis(sessions, done)
    set_analysis(
        sessions, analysis, status=RunStatus.FAILED, finished_at=NOW - timedelta(hours=2), error="c"
    )

    activity = service.snapshot()

    assert [(job.kind, job.error) for job in activity.failures] == [
        (JobKind.RUN, "b"),
        (JobKind.ANALYSIS, "c"),
        (JobKind.RUN, "a"),
    ]
    assert activity.failures[0].attempt == 3
    assert activity.failures[1].subject.analysis == ZigzagAnalysisConfig(epsilons=(0.1,))
    assert activity.finished == {
        JobKind.RUN: {RunStatus.FAILED: 1, RunStatus.COMPLETED: 1, RunStatus.CANCELLED: 1},
        JobKind.ANALYSIS: {RunStatus.FAILED: 1},
    }


def test_activity_endpoint(
    client: TestClient, sessions: sessionmaker[Session], monitor: FakeMonitor
) -> None:
    run_id, queued = add_experiment(sessions, n_runs=2)
    started = datetime.now(UTC)
    set_run(
        sessions,
        run_id,
        status=RunStatus.RUNNING,
        attempt=1,
        started_at=started,
        heartbeat_at=started,
    )
    monitor.state = queue_state(
        (JobRef(JobKind.RUN, queued, 1),), worker("w1", JobRef(JobKind.RUN, run_id, 1))
    )
    monitor.watchdog_state = WatchdogState(
        swept_at=started,
        interval_seconds=10.0,
        recoveries=(RecoveryRecord(started, JobRef(JobKind.RUN, run_id, 2), "retried"),),
    )

    response = client.get("/api/activity")

    assert response.status_code == 200
    body = response.json()
    assert body["queue"] | {"waiting": 1, "started": 1} == body["queue"]
    [worker_out] = body["workers"]
    assert worker_out["job"] == {"kind": "run", "id": str(run_id), "attempt": 1}
    assert worker_out["job_status"] == "running"
    assert worker_out["subject"]["run_index"] == 0
    [job] = body["running"]
    assert (job["worker"], job["lease"], job["subject"]["analysis"]) == ("w1", "healthy", None)
    [group] = body["waiting"]
    assert (group["run_indices"], group["next_position"], group["missing"]) == ([1], 1, 0)
    [recovery] = body["watchdog"]["recoveries"]
    assert recovery["action"] == "retried"
    assert recovery["subject"] | {"run_id": str(run_id), "run_index": 0} == recovery["subject"]
    assert body["limits"]["lease_timeout_seconds"] == 60.0
    assert {row["kind"] for row in body["finished"]} == {"run", "analysis"}
