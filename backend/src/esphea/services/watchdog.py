"""Recovery of jobs orphaned by lost workers or a lost job queue."""

import logging
import shutil
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from esphea.experiments.storage import snapshot_directory
from esphea.messaging.events import run_status_event
from esphea.messaging.ports import EventPublisher, JobKind, JobQueue, JobRef
from esphea.persistence.models import AnalysisRow, LeasedJob, RunRow, RunStatus
from esphea.persistence.repositories import (
    AnalysisRepository,
    LeasedJobRepository,
    MetricsRepository,
    RunRepository,
)
from esphea.topology.storage import analysis_directory

logger = logging.getLogger(__name__)


class RecoveryAction(StrEnum):
    RETRIED = "retried"
    FAILED = "failed"
    REENQUEUED = "reenqueued"


@dataclass(frozen=True, slots=True)
class Recovery:
    kind: JobKind
    job_id: str
    action: RecoveryAction
    attempt: int


class RecoverableJobs(ABC):
    """Recovery policy of one kind of leased job."""

    kind: JobKind

    @abstractmethod
    def repository(self, session: Session) -> LeasedJobRepository[Any]: ...

    def discard_partial_results(self, session: Session, job: Any) -> list[Path]:
        """Delete what the lost attempt wrote to the database; return directories to remove."""
        return []

    def notify(self, job: Any, status: RunStatus, error: str | None) -> None:  # noqa: B027
        """Announce the new status of a recovered job (optional hook; best effort)."""


class RunJobs(RecoverableJobs):
    kind = JobKind.RUN

    def __init__(self, *, runs_dir: Path, publisher: EventPublisher) -> None:
        self._runs_dir = runs_dir
        self._publisher = publisher

    def repository(self, session: Session) -> RunRepository:
        return RunRepository(session)

    def discard_partial_results(self, session: Session, job: RunRow) -> list[Path]:
        MetricsRepository(session).delete_for_run(job.id)
        return [snapshot_directory(self._runs_dir, job.id, job.attempt)]

    def notify(self, job: RunRow, status: RunStatus, error: str | None) -> None:
        event = run_status_event(
            job.experiment_id, job.id, status, attempt=job.attempt, error=error
        )
        try:
            self._publisher.publish(job.experiment_id, event)
        except Exception:
            logger.warning("could not publish status of run %s", job.id, exc_info=True)


class AnalysisJobs(RecoverableJobs):
    kind = JobKind.ANALYSIS

    def __init__(self, *, runs_dir: Path) -> None:
        self._runs_dir = runs_dir

    def repository(self, session: Session) -> AnalysisRepository:
        return AnalysisRepository(session)

    def discard_partial_results(self, session: Session, job: AnalysisRow) -> list[Path]:
        return [analysis_directory(self._runs_dir, job.run_id, job.id, job.attempt)]


@dataclass(slots=True)
class _Plan:
    """Side effects to perform once the database transaction has committed."""

    recoveries: list[Recovery] = field(default_factory=list)
    enqueue: list[JobRef] = field(default_factory=list)
    notifications: list[tuple[RecoverableJobs, LeasedJob, RunStatus, str | None]] = field(
        default_factory=list
    )
    stale_dirs: list[Path] = field(default_factory=list)


class Watchdog:
    """Periodically repairs leased jobs that no live worker is taking care of.

    * A **running** job whose lease (heartbeat) expired lost its worker. Its
      partial results are discarded and it is queued again for a new attempt,
      up to ``max_attempts``; after that it is marked failed.
    * A **queued** job whose queue entry no longer exists (e.g. Redis was
      restarted) is enqueued again; this does not count as an attempt.

    Rows are locked with ``SKIP LOCKED``, so several watchdogs never act on the
    same job, and attempts fence the workers' writes (see ``LeasedJobRepository``).
    """

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        queue: JobQueue,
        jobs: Sequence[RecoverableJobs],
        lease_timeout: timedelta,
        max_attempts: int,
        enqueue_grace: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._sessions = sessions
        self._queue = queue
        self._jobs = tuple(jobs)
        self._lease_timeout = lease_timeout
        self._max_attempts = max_attempts
        self._enqueue_grace = enqueue_grace
        self._clock = clock

    def sweep(self) -> list[Recovery]:
        recoveries: list[Recovery] = []
        for jobs in self._jobs:
            recoveries.extend(self._sweep(jobs))
        return recoveries

    def _sweep(self, jobs: RecoverableJobs) -> list[Recovery]:
        plan = _Plan()
        now = self._clock()
        with self._sessions.begin() as session:
            repository = jobs.repository(session)
            for job in repository.lock_stale_running(now - self._lease_timeout):
                self._recover_lost_worker(jobs, session, repository, job, plan)
            for job in repository.lock_queued_before(now - self._enqueue_grace):
                ref = JobRef(jobs.kind, job.id, job.attempt + 1)
                if not self._queue.is_enqueued(ref):
                    repository.mark_enqueued(job)
                    plan.enqueue.append(ref)
                    plan.recoveries.append(
                        Recovery(jobs.kind, str(job.id), RecoveryAction.REENQUEUED, ref.attempt)
                    )
        self._apply(plan)
        return plan.recoveries

    def _recover_lost_worker(
        self,
        jobs: RecoverableJobs,
        session: Session,
        repository: LeasedJobRepository[Any],
        job: LeasedJob,
        plan: _Plan,
    ) -> None:
        lost = job.attempt
        plan.stale_dirs.extend(jobs.discard_partial_results(session, job))
        if lost < self._max_attempts:
            repository.requeue(job, f"worker lost during attempt {lost}; retrying")
            plan.enqueue.append(JobRef(jobs.kind, job.id, lost + 1))
            plan.notifications.append((jobs, job, RunStatus.QUEUED, job.error))
            plan.recoveries.append(
                Recovery(jobs.kind, str(job.id), RecoveryAction.RETRIED, lost + 1)
            )
        else:
            error = f"worker lost during attempt {lost} of {self._max_attempts}"
            repository.fail(job, error)
            plan.notifications.append((jobs, job, RunStatus.FAILED, error))
            plan.recoveries.append(Recovery(jobs.kind, str(job.id), RecoveryAction.FAILED, lost))

    def _apply(self, plan: _Plan) -> None:
        for directory in plan.stale_dirs:
            shutil.rmtree(directory, ignore_errors=True)
        for ref in plan.enqueue:
            try:
                self._queue.enqueue(ref)
            except Exception:  # retried on the next sweep (the job stays queued)
                logger.exception(
                    "could not enqueue %s %s attempt %d", ref.kind, ref.entity_id, ref.attempt
                )
        for jobs, job, status, error in plan.notifications:
            jobs.notify(job, status, error)
        for recovery in plan.recoveries:
            logger.warning(
                "%s %s: %s (attempt %d)",
                recovery.kind,
                recovery.job_id,
                recovery.action,
                recovery.attempt,
            )
