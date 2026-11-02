"""Recovery of runs orphaned by lost workers or a lost job queue."""

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from esphea.experiments.storage import snapshot_directory
from esphea.messaging.events import run_status_event
from esphea.messaging.ports import EventPublisher, JobQueue
from esphea.persistence.models import RunRow, RunStatus
from esphea.persistence.repositories import MetricsRepository, RunRepository

logger = logging.getLogger(__name__)


class RecoveryAction(StrEnum):
    RETRIED = "retried"
    FAILED = "failed"
    REENQUEUED = "reenqueued"


@dataclass(frozen=True, slots=True)
class Recovery:
    run_id: str
    action: RecoveryAction
    attempt: int


@dataclass(slots=True)
class _Plan:
    """Side effects to perform once the database transaction has committed."""

    recoveries: list[Recovery] = field(default_factory=list)
    enqueue: list[tuple[RunRow, int]] = field(default_factory=list)
    events: list[tuple[RunRow, RunStatus, str | None]] = field(default_factory=list)
    stale_dirs: list[Path] = field(default_factory=list)


class RunWatchdog:
    """Periodically repairs runs that no live worker is taking care of.

    * A **running** run whose lease (heartbeat) expired lost its worker. Its
      partial metrics and snapshots are discarded and it is queued again for a
      new attempt, up to ``max_attempts``; after that it is marked failed.
    * A **queued** run whose job no longer exists in the queue (e.g. Redis was
      restarted) is enqueued again; this does not count as an attempt.

    Rows are locked with ``SKIP LOCKED``, so several watchdogs never act on the
    same run, and attempts fence the workers' writes (see ``RunRepository``).
    """

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        queue: JobQueue,
        publisher: EventPublisher,
        runs_dir: Path,
        lease_timeout: timedelta,
        max_attempts: int,
        enqueue_grace: timedelta,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        self._sessions = sessions
        self._queue = queue
        self._publisher = publisher
        self._runs_dir = runs_dir
        self._lease_timeout = lease_timeout
        self._max_attempts = max_attempts
        self._enqueue_grace = enqueue_grace
        self._clock = clock

    def sweep(self) -> list[Recovery]:
        plan = _Plan()
        now = self._clock()
        with self._sessions.begin() as session:
            runs = RunRepository(session)
            metrics = MetricsRepository(session)
            for run in runs.lock_stale_running(now - self._lease_timeout):
                self._recover_lost_worker(run, runs, metrics, plan)
            for run in runs.lock_queued_before(now - self._enqueue_grace):
                if not self._queue.is_enqueued(run.id, run.attempt + 1):
                    runs.mark_enqueued(run)
                    plan.enqueue.append((run, run.attempt + 1))
                    plan.recoveries.append(
                        Recovery(str(run.id), RecoveryAction.REENQUEUED, run.attempt + 1)
                    )
        self._apply(plan)
        return plan.recoveries

    def _recover_lost_worker(
        self, run: RunRow, runs: RunRepository, metrics: MetricsRepository, plan: _Plan
    ) -> None:
        lost = run.attempt
        metrics.delete_for_run(run.id)
        plan.stale_dirs.append(snapshot_directory(self._runs_dir, run.id, lost))
        if lost < self._max_attempts:
            runs.requeue(run, f"worker lost during attempt {lost}; retrying")
            plan.enqueue.append((run, lost + 1))
            plan.events.append((run, RunStatus.QUEUED, run.error))
            plan.recoveries.append(Recovery(str(run.id), RecoveryAction.RETRIED, lost + 1))
        else:
            error = f"worker lost during attempt {lost} of {self._max_attempts}"
            runs.fail(run, error)
            plan.events.append((run, RunStatus.FAILED, error))
            plan.recoveries.append(Recovery(str(run.id), RecoveryAction.FAILED, lost))

    def _apply(self, plan: _Plan) -> None:
        for directory in plan.stale_dirs:
            shutil.rmtree(directory, ignore_errors=True)
        for run, attempt in plan.enqueue:
            try:
                self._queue.enqueue_run(run.id, attempt)
            except Exception:  # retried on the next sweep (the run stays queued)
                logger.exception("could not enqueue run %s attempt %d", run.id, attempt)
        for run, status, error in plan.events:
            event = run_status_event(
                run.experiment_id, run.id, status, attempt=run.attempt, error=error
            )
            try:
                self._publisher.publish(run.experiment_id, event)
            except Exception:
                logger.warning("could not publish status of run %s", run.id, exc_info=True)
        for recovery in plan.recoveries:
            logger.warning(
                "run %s: %s (attempt %d)", recovery.run_id, recovery.action, recovery.attempt
            )
