"""Fakes of the messaging ports and an in-process application for integration tests."""

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any, Protocol

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from esphea.api.app import create_app
from esphea.api.infrastructure import Infrastructure
from esphea.experiments.registry import default_algorithm_registry, default_problem_registry
from esphea.experiments.runner import RunExecutor
from esphea.messaging.ports import JobKind, JobRef
from esphea.persistence.db import create_db_engine, create_session_factory
from esphea.persistence.models import Base
from esphea.services.execution import RunService
from esphea.settings import Settings


class FakeFlags:
    def __init__(self) -> None:
        self.requested: set[uuid.UUID] = set()

    def request(self, run_id: uuid.UUID) -> None:
        self.requested.add(run_id)

    def is_requested(self, run_id: uuid.UUID) -> bool:
        return run_id in self.requested

    def clear(self, run_id: uuid.UUID) -> None:
        self.requested.discard(run_id)


class FakePublisher:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def publish(self, experiment_id: uuid.UUID, event: dict[str, Any]) -> None:
        self.events.append(event)


class FakeSubscriber:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages

    async def subscribe(self, experiment_id: uuid.UUID) -> AsyncIterator[str]:
        for message in self.messages:
            yield message


class Executor(Protocol):
    def execute(self, entity_id: uuid.UUID, attempt: int) -> object: ...


class RecordingQueue:
    """Remembers enqueued jobs; ``executors`` make it run them synchronously by kind."""

    def __init__(self) -> None:
        self.enqueued: list[JobRef] = []
        self.cancelled: list[JobRef] = []
        self.pending: set[JobRef] = set()
        self.executors: dict[JobKind, Executor] = {}

    def enqueue(self, job: JobRef) -> None:
        self.enqueued.append(job)
        self.pending.add(job)
        executor = self.executors.get(job.kind)
        if executor is not None:
            self.pending.discard(job)
            executor.execute(job.entity_id, job.attempt)

    def cancel(self, job: JobRef) -> None:
        self.cancelled.append(job)
        self.pending.discard(job)

    def is_enqueued(self, job: JobRef) -> bool:
        return job in self.pending

    def runs(self) -> list[tuple[uuid.UUID, int]]:
        return [(job.entity_id, job.attempt) for job in self.enqueued if job.kind == JobKind.RUN]


@pytest.fixture
def sessions(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    return create_session_factory(engine)


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    return tmp_path / "runs"


@pytest.fixture
def flags() -> FakeFlags:
    return FakeFlags()


@pytest.fixture
def publisher() -> FakePublisher:
    return FakePublisher()


@pytest.fixture
def queue() -> RecordingQueue:
    return RecordingQueue()


@pytest.fixture
def run_service(
    sessions: sessionmaker[Session], publisher: FakePublisher, flags: FakeFlags, runs_dir: Path
) -> RunService:
    return RunService(
        sessions,
        executor=RunExecutor(default_problem_registry(), default_algorithm_registry()),
        publisher=publisher,
        cancellation=flags,
        runs_dir=runs_dir,
    )


@pytest.fixture
def subscriber() -> FakeSubscriber:
    return FakeSubscriber([])


@pytest.fixture
def client(
    sessions: sessionmaker[Session],
    queue: RecordingQueue,
    flags: FakeFlags,
    publisher: FakePublisher,
    subscriber: FakeSubscriber,
    runs_dir: Path,
) -> Iterator[TestClient]:
    infrastructure = Infrastructure(
        sessions=sessions,
        queue=queue,
        cancellation=flags,
        publisher=publisher,
        subscriber=subscriber,
        problems=default_problem_registry(),
        runs_dir=runs_dir,
    )
    app = create_app(infrastructure, Settings(cors_origins=[]))
    with TestClient(app) as test_client:
        yield test_client
