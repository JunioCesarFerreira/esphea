"""Messaging ports: the application depends on these, not on Redis or RQ."""

import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
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


# --- observability -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WorkerState:
    """A worker process registered with the job queue.

    Fields the queue no longer holds (e.g. after its registry entry expired while
    the host was suspended) are ``None`` and the state is ``"unknown"``.
    """

    name: str
    state: str  # "busy", "idle", "suspended", "started", ... or "unknown"
    hostname: str | None
    pid: int | None
    job: JobRef | None  # the job it is executing
    born_at: datetime | None
    seen_at: datetime | None  # last heartbeat
    successful_jobs: int
    failed_jobs: int
    working_seconds: float


@dataclass(frozen=True, slots=True)
class QueueState:
    name: str
    waiting: tuple[JobRef, ...]  # in the order workers will take them
    started: int
    failed: int
    finished: int  # kept for an hour
    deferred: int
    scheduled: int
    workers: tuple[WorkerState, ...]


@dataclass(frozen=True, slots=True)
class RecoveryRecord:
    """A job the watchdog repaired (see :mod:`esphea.services.watchdog`)."""

    at: datetime
    job: JobRef  # attempt: the new attempt, or the last one when the job failed
    action: str  # "retried", "failed" or "reenqueued"


@dataclass(frozen=True, slots=True)
class WatchdogState:
    swept_at: datetime
    interval_seconds: float
    recoveries: tuple[RecoveryRecord, ...]  # most recent first


class ActivityMonitor(Protocol):
    """Read-only view of the workers, the job queue and the watchdog."""

    def queue(self) -> QueueState: ...

    def watchdog(self) -> WatchdogState | None:
        """The last sweep reported by the watchdog; ``None`` if it never reported."""
        ...


class WatchdogReporter(Protocol):
    def report_sweep(
        self, at: datetime, interval_seconds: float, recoveries: Sequence[RecoveryRecord]
    ) -> None: ...
