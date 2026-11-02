import time
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker

from esphea.experiments.config import ExperimentConfig, NSGA2Config
from esphea.experiments.registry import default_algorithm_registry, default_problem_registry
from esphea.experiments.runner import RunExecutor, RunOutcome
from esphea.experiments.storage import SnapshotReader, snapshot_directory
from esphea.persistence.models import RunStatus
from esphea.persistence.repositories import (
    ExperimentRepository,
    MetricsRepository,
    RunRepository,
)
from esphea.services.execution import RunService, ThrottledCheck
from esphea.services.leases import Lease, database_renewal
from tests.integration.conftest import FakeFlags, FakePublisher


def add_experiment(sessions: sessionmaker[Session], n_gen: int = 5) -> uuid.UUID:
    config = ExperimentConfig(name="t", algorithm=NSGA2Config(pop_size=12), n_gen=n_gen)
    with sessions.begin() as session:
        return ExperimentRepository(session).add(config).runs[0].id


def load(sessions: sessionmaker[Session], run_id: uuid.UUID) -> Any:
    with sessions() as session:
        run = RunRepository(session).get(run_id)
        assert run is not None
        return run


def make_service(
    sessions: sessionmaker[Session],
    executor: RunExecutor,
    publisher: FakePublisher,
    flags: FakeFlags,
    runs_dir: Path,
) -> RunService:
    return RunService(
        sessions, executor=executor, publisher=publisher, cancellation=flags, runs_dir=runs_dir
    )


def default_executor() -> RunExecutor:
    return RunExecutor(default_problem_registry(), default_algorithm_registry())


def test_attempt_runs_only_once(
    sessions: sessionmaker[Session], run_service: RunService, runs_dir: Path
) -> None:
    run_id = add_experiment(sessions)
    assert run_service.execute(run_id, 1) == RunStatus.COMPLETED
    assert run_service.execute(run_id, 1) is None
    assert run_service.execute(run_id, 2) is None
    run = load(sessions, run_id)
    assert (run.status, run.attempt, run.generation) == (RunStatus.COMPLETED, 1, 5)
    assert SnapshotReader(snapshot_directory(runs_dir, run_id, 1)).generations() == list(range(6))


def test_claim_requires_the_next_attempt(
    sessions: sessionmaker[Session], run_service: RunService
) -> None:
    run_id = add_experiment(sessions)
    assert run_service.execute(run_id, 2) is None
    assert load(sessions, run_id).status == RunStatus.QUEUED


def test_cooperative_cancellation(
    sessions: sessionmaker[Session], run_service: RunService, flags: FakeFlags
) -> None:
    run_id = add_experiment(sessions, n_gen=100_000)
    flags.request(run_id)
    assert run_service.execute(run_id, 1) == RunStatus.CANCELLED
    assert flags.requested == set()  # flag cleared after the run


class ExplodingExecutor(RunExecutor):
    def __init__(self) -> None:
        super().__init__(default_problem_registry(), default_algorithm_registry())

    def execute(self, *args: Any, **kwargs: Any) -> RunOutcome:
        raise RuntimeError("boom")


def test_failures_are_recorded(
    sessions: sessionmaker[Session], publisher: FakePublisher, flags: FakeFlags, runs_dir: Path
) -> None:
    run_id = add_experiment(sessions)
    service = make_service(sessions, ExplodingExecutor(), publisher, flags, runs_dir)
    assert service.execute(run_id, 1) == RunStatus.FAILED
    assert load(sessions, run_id).error == "RuntimeError: boom"
    assert publisher.events[-1]["status"] == "failed"
    assert publisher.events[-1]["attempt"] == 1


class RecoveredMidRunExecutor(RunExecutor):
    """Simulates the watchdog taking the run away while the attempt is executing."""

    def __init__(self, sessions: sessionmaker[Session], run_id: uuid.UUID) -> None:
        super().__init__(default_problem_registry(), default_algorithm_registry())
        self._sessions = sessions
        self._run_id = run_id

    def execute(self, *args: Any, **kwargs: Any) -> RunOutcome:
        with self._sessions.begin() as session:
            run = RunRepository(session).get(self._run_id)
            assert run is not None
            RunRepository(session).requeue(run, "worker lost")
        return super().execute(*args, **kwargs)


def test_attempt_that_lost_its_run_leaves_it_untouched(
    sessions: sessionmaker[Session], publisher: FakePublisher, flags: FakeFlags, runs_dir: Path
) -> None:
    run_id = add_experiment(sessions, n_gen=50)
    executor = RecoveredMidRunExecutor(sessions, run_id)
    service = make_service(sessions, executor, publisher, flags, runs_dir)

    assert service.execute(run_id, 1) is None
    run = load(sessions, run_id)
    assert (run.status, run.attempt, run.generation) == (RunStatus.QUEUED, 1, 0)
    with sessions() as session:
        assert MetricsRepository(session).for_runs([run_id]) == []
    # Only the claim was announced: no progress or terminal event after losing the run.
    assert [e["type"] for e in publisher.events] == ["run.status"]
    assert publisher.events[0]["status"] == "running"


def test_finish_is_fenced_by_attempt(sessions: sessionmaker[Session]) -> None:
    run_id = add_experiment(sessions)
    with sessions.begin() as session:
        runs = RunRepository(session)
        assert runs.claim(run_id, 1)
        assert not runs.finish(run_id, 2, RunStatus.COMPLETED)
        assert runs.finish(run_id, 1, RunStatus.COMPLETED)


def test_lease_is_lost_when_the_run_is_recovered(sessions: sessionmaker[Session]) -> None:
    run_id = add_experiment(sessions)
    with sessions.begin() as session:
        RunRepository(session).claim(run_id, 1)
    lease = run_lease(sessions, run_id, interval=1)
    assert lease.renew()
    with sessions.begin() as session:
        run = RunRepository(session).get(run_id)
        assert run is not None
        RunRepository(session).requeue(run, "worker lost")
    assert not lease.renew()
    assert lease.lost


def run_lease(sessions: sessionmaker[Session], run_id: uuid.UUID, interval: float) -> Lease:
    return Lease(
        database_renewal(sessions, RunRepository, run_id, 1),
        name="test",
        interval=interval,
        self_fence_after=10 * interval,
    )


def unreachable_database() -> bool:
    raise ConnectionError("database unreachable")


def test_lease_self_fences_without_successful_heartbeats() -> None:
    now = [0.0]
    lease = Lease(
        unreachable_database, name="test", interval=1, self_fence_after=10, clock=lambda: now[0]
    )
    now[0] = 5
    assert lease.renew()  # failures are tolerated within the deadline
    now[0] = 10
    assert not lease.renew()
    assert lease.lost


def test_lease_thread_renews_heartbeat(sessions: sessionmaker[Session]) -> None:
    run_id = add_experiment(sessions)
    with sessions.begin() as session:
        RunRepository(session).claim(run_id, 1)
    before = load(sessions, run_id).heartbeat_at
    lease = run_lease(sessions, run_id, interval=0.05)
    lease.start()
    try:
        time.sleep(0.2)
    finally:
        lease.stop()
    assert load(sessions, run_id).heartbeat_at > before
    assert not lease.lost


@pytest.mark.parametrize(("answers", "expected"), [([False, True], True), ([False, False], False)])
def test_throttled_check(answers: list[bool], expected: bool) -> None:
    now = [0.0]
    calls = iter(answers)
    check = ThrottledCheck(lambda: next(calls), interval=1.0, clock=lambda: now[0])
    assert check() is False
    now[0] = 0.5
    assert check() is False  # throttled: not called
    now[0] = 1.5
    assert check() is expected
