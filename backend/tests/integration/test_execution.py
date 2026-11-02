import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from esphea.experiments.config import ExperimentConfig, NSGA2Config
from esphea.experiments.registry import default_algorithm_registry, default_problem_registry
from esphea.experiments.runner import RunExecutor
from esphea.persistence.models import RunStatus
from esphea.persistence.repositories import ExperimentRepository, RunRepository
from esphea.services.execution import RunService, ThrottledCheck
from tests.integration.conftest import FakeFlags, FakePublisher


def add_experiment(sessions: sessionmaker[Session], n_gen: int = 5) -> uuid.UUID:
    config = ExperimentConfig(name="t", algorithm=NSGA2Config(pop_size=12), n_gen=n_gen)
    with sessions.begin() as session:
        return ExperimentRepository(session).add(config).runs[0].id


def status_of(sessions: sessionmaker[Session], run_id: uuid.UUID) -> RunStatus:
    with sessions() as session:
        run = RunRepository(session).get(run_id)
        assert run is not None
        return run.status


def test_runs_only_once(sessions: sessionmaker[Session], run_service: RunService) -> None:
    run_id = add_experiment(sessions)
    assert run_service.execute(run_id) == RunStatus.COMPLETED
    assert run_service.execute(run_id) is None


def test_cooperative_cancellation(
    sessions: sessionmaker[Session], run_service: RunService, flags: FakeFlags
) -> None:
    run_id = add_experiment(sessions, n_gen=100_000)
    flags.request(run_id)
    assert run_service.execute(run_id) == RunStatus.CANCELLED
    assert flags.requested == set()  # flag cleared after the run


class ExplodingExecutor(RunExecutor):
    def __init__(self) -> None:
        super().__init__(default_problem_registry(), default_algorithm_registry())

    def execute(self, *args: object, **kwargs: object) -> object:  # type: ignore[override]
        raise RuntimeError("boom")


def test_failures_are_recorded(
    sessions: sessionmaker[Session],
    publisher: FakePublisher,
    flags: FakeFlags,
    runs_dir: Path,
) -> None:
    run_id = add_experiment(sessions)
    service = RunService(
        sessions,
        executor=ExplodingExecutor(),
        publisher=publisher,
        cancellation=flags,
        runs_dir=runs_dir,
    )
    assert service.execute(run_id) == RunStatus.FAILED
    with sessions() as session:
        run = RunRepository(session).get(run_id)
        assert run is not None
        assert run.error == "RuntimeError: boom"
    assert publisher.events[-1]["status"] == "failed"


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
