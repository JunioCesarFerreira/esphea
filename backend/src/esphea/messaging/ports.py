"""Messaging ports: the application depends on these, not on Redis or RQ."""

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class JobKind(StrEnum):
    RUN = "run"
    ANALYSIS = "analysis"


@dataclass(frozen=True, slots=True)
class JobRef:
    """One execution attempt of a leased job (each attempt is a distinct queue job)."""

    kind: JobKind
    entity_id: uuid.UUID
    attempt: int


class JobQueue(Protocol):
    def enqueue(self, job: JobRef) -> None:
        """Schedule ``job`` for execution by a worker."""
        ...

    def cancel(self, job: JobRef) -> None:
        """Drop a job that has not been picked by a worker yet (no-op otherwise)."""
        ...

    def is_enqueued(self, job: JobRef) -> bool:
        """Whether ``job`` is still waiting for (or held by) a worker."""
        ...


class CancellationFlags(Protocol):
    """Cooperative cancellation of running runs."""

    def request(self, run_id: uuid.UUID) -> None: ...

    def is_requested(self, run_id: uuid.UUID) -> bool: ...

    def clear(self, run_id: uuid.UUID) -> None: ...


class EventPublisher(Protocol):
    def publish(self, experiment_id: uuid.UUID, event: dict[str, Any]) -> None:
        """Broadcast a JSON-serialisable event to the experiment's subscribers."""
        ...


class EventSubscriber(Protocol):
    def subscribe(self, experiment_id: uuid.UUID) -> AsyncIterator[str]:
        """Yield the JSON-encoded events of an experiment as they are published."""
        ...
