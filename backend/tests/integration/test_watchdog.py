import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from esphea.experiments.config import ExperimentConfig, NSGA2Config
from esphea.experiments.observers import GenerationMetrics
from esphea.experiments.registry import default_problem_registry
from esphea.experiments.storage import snapshot_directory
from esphea.messaging.ports import JobKind, JobRef
from esphea.persistence.models import RunRow, RunStatus
from esphea.persistence.repositories import ExperimentRepository, MetricsRepository, RunRepository
from esphea.services.execution import RunService
from esphea.services.results import ResultsService
from esphea.services.watchdog import RecoveryAction, RunJobs, Watchdog
from tests.integration.conftest import FakePublisher, RecordingQueue

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
LEASE = timedelta(seconds=60)
GRACE = timedelta(seconds=120)


@pytest.fixture
def watchdog(
    sessions: sessionmaker[Session], queue: RecordingQueue, publisher: FakePublisher, runs_dir: Path
) -> Watchdog:
    return Watchdog(
        sessions,
        queue=queue,
        jobs=[RunJobs(runs_dir=runs_dir, publisher=publisher)],
        lease_timeout=LEASE,
        max_attempts=3,
        enqueue_grace=GRACE,
        clock=lambda: NOW,
    )


def add_run(sessions: sessionmaker[Session], n_gen: int = 5) -> uuid.UUID:
    config = ExperimentConfig(name="t", algorithm=NSGA2Config(pop_size=12), n_gen=n_gen)
    with sessions.begin() as session:
        return ExperimentRepository(session).add(config).runs[0].id


def set_columns(sessions: sessionmaker[Session], run_id: uuid.UUID, **values: Any) -> None:
    with sessions.begin() as session:
        session.execute(update(RunRow).where(RunRow.id == run_id).values(**values))


def run_of(sessions: sessionmaker[Session], run_id: uuid.UUID) -> RunRow:
    with sessions() as session:
        run = RunRepository(session).get(run_id)
        assert run is not None
        return run


def orphan(
    sessions: sessionmaker[Session], runs_dir: Path, attempt: int, heartbeat_age: timedelta
) -> uuid.UUID:
    """A run claimed by ``attempt`` whose worker stopped sending heartbeats."""
    run_id = add_run(sessions)
    set_columns(
        sessions,
        run_id,
        status=RunStatus.RUNNING,
        attempt=attempt,
        generation=3,
        heartbeat_at=NOW - heartbeat_age,
    )
    with sessions.begin() as session:
        MetricsRepository(session).add_many(run_id, [GenerationMetrics(0, 4, 0.1, {"igd": 1.0})])
    directory = snapshot_directory(runs_dir, run_id, attempt)
    directory.mkdir(parents=True)
    (directory / "part-00000.parquet").write_bytes(b"partial")
    return run_id


def test_lost_worker_is_retried(
    sessions: sessionmaker[Session],
    watchdog: Watchdog,
    queue: RecordingQueue,
    publisher: FakePublisher,
    runs_dir: Path,
) -> None:
    run_id = orphan(sessions, runs_dir, attempt=1, heartbeat_age=LEASE + timedelta(seconds=1))

    [recovery] = watchdog.sweep()

    assert (recovery.action, recovery.attempt) == (RecoveryAction.RETRIED, 2)
    run = run_of(sessions, run_id)
    assert (run.status, run.attempt, run.generation) == (RunStatus.QUEUED, 1, 0)
    assert run.error == "worker lost during attempt 1; retrying"
    assert queue.runs() == [(run_id, 2)]
    assert not snapshot_directory(runs_dir, run_id, 1).exists()
    with sessions() as session:
        assert MetricsRepository(session).for_runs([run_id]) == []
    assert publisher.events[-1] | {"status": "queued", "attempt": 1} == publisher.events[-1]


def test_gives_up_after_the_last_attempt(
    sessions: sessionmaker[Session], watchdog: Watchdog, queue: RecordingQueue, runs_dir: Path
) -> None:
    run_id = orphan(sessions, runs_dir, attempt=3, heartbeat_age=LEASE * 2)

    [recovery] = watchdog.sweep()

    assert recovery.action == RecoveryAction.FAILED
    run = run_of(sessions, run_id)
    assert run.status == RunStatus.FAILED
    assert run.error == "worker lost during attempt 3 of 3"
    assert queue.enqueued == []


def test_live_workers_are_left_alone(
    sessions: sessionmaker[Session], watchdog: Watchdog, runs_dir: Path
) -> None:
    run_id = orphan(sessions, runs_dir, attempt=1, heartbeat_age=LEASE - timedelta(seconds=1))
    assert watchdog.sweep() == []
    assert run_of(sessions, run_id).status == RunStatus.RUNNING
    assert snapshot_directory(runs_dir, run_id, 1).exists()


def test_queued_run_with_missing_job_is_enqueued_again(
    sessions: sessionmaker[Session], watchdog: Watchdog, queue: RecordingQueue
) -> None:
    lost_job = add_run(sessions)
    pending_job = add_run(sessions)
    recent = add_run(sessions)
    old = NOW - GRACE - timedelta(seconds=1)
    set_columns(sessions, lost_job, enqueued_at=old)
    set_columns(sessions, pending_job, enqueued_at=old)
    set_columns(sessions, recent, enqueued_at=NOW)
    queue.pending.add(JobRef(JobKind.RUN, pending_job, 1))

    [recovery] = watchdog.sweep()

    assert (recovery.job_id, recovery.action) == (str(lost_job), RecoveryAction.REENQUEUED)
    assert queue.runs() == [(lost_job, 1)]
    enqueued_at = run_of(sessions, lost_job).enqueued_at
    assert enqueued_at is not None
    assert enqueued_at.replace(tzinfo=UTC) > old


def test_retry_completes_and_results_follow_the_new_attempt(
    sessions: sessionmaker[Session],
    watchdog: Watchdog,
    queue: RecordingQueue,
    run_service: RunService,
    runs_dir: Path,
) -> None:
    run_id = orphan(sessions, runs_dir, attempt=1, heartbeat_age=LEASE * 2)
    queue.executors[JobKind.RUN] = run_service  # the retry runs inline when enqueued

    watchdog.sweep()

    run = run_of(sessions, run_id)
    assert (run.status, run.attempt, run.error) == (RunStatus.COMPLETED, 2, None)
    with sessions() as session:
        results = ResultsService(session, problems=default_problem_registry(), runs_dir=runs_dir)
        assert results.stored_generations(run_id) == list(range(6))
        assert results.run_metrics(run_id).generation == list(range(6))
