"""Messaging ports: the application depends on these, not on Redis or RQ."""

import uuid
from collections.abc import AsyncIterator
from typing import Any, Protocol


class JobQueue(Protocol):
    """Schedules execution attempts; each attempt of a run is a distinct job."""

    def enqueue_run(self, run_id: uuid.UUID, attempt: int) -> None:
        """Schedule ``attempt`` of a run for execution by a worker."""
        ...

    def cancel_run(self, run_id: uuid.UUID, attempt: int) -> None:
        """Drop an attempt that has not been picked by a worker yet (no-op otherwise)."""
        ...

    def is_enqueued(self, run_id: uuid.UUID, attempt: int) -> bool:
        """Whether the job of ``attempt`` is still waiting for (or held by) a worker."""
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
