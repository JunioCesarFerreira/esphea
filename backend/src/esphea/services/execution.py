"""Worker-side use case: execute one run attempt and record everything about it."""

import logging
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from esphea.experiments.config import ExperimentConfig
from esphea.experiments.observers import GenerationMetrics, RunProgress
from esphea.experiments.runner import RunExecutor
from esphea.experiments.storage import snapshot_directory
from esphea.messaging.events import run_progress_event, run_status_event
from esphea.messaging.ports import CancellationFlags, EventPublisher
from esphea.persistence.models import RunStatus
from esphea.persistence.repositories import MetricsRepository, RunRepository
from esphea.services.leases import Lease, LeaseLostError, database_renewal

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 4000


class DatabaseMetricsSink:
    """Buffers metric rows and writes them in batches (by size or age), fenced by attempt."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        run_id: uuid.UUID,
        attempt: int,
        *,
        max_rows: int = 200,
        max_age_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions = sessions
        self._run_id = run_id
        self._attempt = attempt
        self._max_rows = max_rows
        self._max_age = max_age_seconds
        self._clock = clock
        self._buffer: list[GenerationMetrics] = []
        self._last_flush = clock()

    def add(self, metrics: GenerationMetrics) -> None:
        self._buffer.append(metrics)
        if len(self._buffer) >= self._max_rows or self._clock() - self._last_flush >= self._max_age:
            self.flush()

    def flush(self) -> None:
        self._last_flush = self._clock()
        if not self._buffer:
            return
        with self._sessions.begin() as session:
            if not RunRepository(session).lock_owned(self._run_id, self._attempt):
                raise LeaseLostError(f"run {self._run_id} is no longer owned by this attempt")
            MetricsRepository(session).add_many(self._run_id, self._buffer)
        self._buffer.clear()


class ProgressBridge:
    """Forwards progress to subscribers and keeps the run's generation counter current."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        publisher: EventPublisher,
        *,
        experiment_id: uuid.UUID,
        run_id: uuid.UUID,
        attempt: int,
    ) -> None:
        self._sessions = sessions
        self._publisher = publisher
        self._experiment_id = experiment_id
        self._run_id = run_id
        self._attempt = attempt

    def report(self, progress: RunProgress) -> None:
        with self._sessions.begin() as session:
            owned = RunRepository(session).set_generation(
                self._run_id, self._attempt, progress.generation
            )
        if not owned:
            return  # the run belongs to another attempt now: stay silent
        self._publisher.publish(
            self._experiment_id, run_progress_event(self._experiment_id, self._run_id, progress)
        )


class ThrottledCheck:
    """Calls ``check`` at most once per ``interval`` seconds and latches once it is true."""

    def __init__(
        self,
        check: Callable[[], bool],
        interval: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._check = check
        self._interval = interval
        self._clock = clock
        self._last = -float("inf")
        self._value = False

    def __call__(self) -> bool:
        now = self._clock()
        if not self._value and now - self._last >= self._interval:
            self._last = now
            self._value = self._check()
        return self._value


class RunService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        executor: RunExecutor,
        publisher: EventPublisher,
        cancellation: CancellationFlags,
        runs_dir: Path,
        heartbeat_interval: float = 5.0,
        self_fence_after: float = 30.0,
        cancellation_poll_seconds: float = 0.5,
    ) -> None:
        self._sessions = sessions
        self._executor = executor
        self._publisher = publisher
        self._cancellation = cancellation
        self._runs_dir = runs_dir
        self._heartbeat_interval = heartbeat_interval
        self._self_fence_after = self_fence_after
        self._poll = cancellation_poll_seconds

    def execute(self, run_id: uuid.UUID, attempt: int) -> RunStatus | None:
        """Run ``attempt`` of ``run_id`` if it can be claimed.

        Returns the final status, or None when the attempt was skipped or lost
        its run to the watchdog (in which case it must not touch the run).
        """
        with self._sessions.begin() as session:
            runs = RunRepository(session)
            run = runs.get(run_id)
            if run is None or not runs.claim(run_id, attempt):
                logger.info("run %s attempt %d is not claimable; skipping", run_id, attempt)
                return None
            experiment_id = run.experiment_id
            seed = run.seed
            config = ExperimentConfig.model_validate(run.experiment.config)

        self._publish_status(experiment_id, run_id, RunStatus.RUNNING, attempt, generation=0)
        lease = Lease(
            database_renewal(self._sessions, RunRepository, run_id, attempt),
            name=f"run {run_id}",
            interval=self._heartbeat_interval,
            self_fence_after=self._self_fence_after,
        )
        cancel_requested = ThrottledCheck(
            lambda: self._cancellation.is_requested(run_id), self._poll
        )
        lease.start()
        try:
            outcome = self._executor.execute(
                config,
                seed,
                metrics_sink=DatabaseMetricsSink(self._sessions, run_id, attempt),
                progress=ProgressBridge(
                    self._sessions,
                    self._publisher,
                    experiment_id=experiment_id,
                    run_id=run_id,
                    attempt=attempt,
                ),
                snapshot_dir=snapshot_directory(self._runs_dir, run_id, attempt),
                should_cancel=lambda: lease.lost or cancel_requested(),
            )
        except Exception as exc:
            if lease.lost or isinstance(exc, LeaseLostError):
                logger.warning("run %s attempt %d lost its lease; abandoning", run_id, attempt)
                return None
            logger.exception("run %s failed", run_id)
            error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]
            return self._finish(experiment_id, run_id, attempt, RunStatus.FAILED, error=error)
        finally:
            lease.stop()

        if lease.lost:
            logger.warning("run %s attempt %d lost its lease; abandoning", run_id, attempt)
            return None
        status = RunStatus.CANCELLED if outcome.cancelled else RunStatus.COMPLETED
        return self._finish(experiment_id, run_id, attempt, status, generation=outcome.generations)

    def _finish(
        self,
        experiment_id: uuid.UUID,
        run_id: uuid.UUID,
        attempt: int,
        status: RunStatus,
        *,
        generation: int | None = None,
        error: str | None = None,
    ) -> RunStatus | None:
        with self._sessions.begin() as session:
            owned = RunRepository(session).finish(
                run_id, attempt, status, generation=generation, error=error
            )
        if not owned:
            logger.warning("run %s attempt %d finished after losing its lease", run_id, attempt)
            return None
        self._cancellation.clear(run_id)
        self._publish_status(
            experiment_id, run_id, status, attempt, generation=generation, error=error
        )
        return status

    def _publish_status(
        self,
        experiment_id: uuid.UUID,
        run_id: uuid.UUID,
        status: RunStatus,
        attempt: int,
        *,
        generation: int | None = None,
        error: str | None = None,
    ) -> None:
        event = run_status_event(
            experiment_id, run_id, status, attempt=attempt, generation=generation, error=error
        )
        try:
            self._publisher.publish(experiment_id, event)
        except Exception:  # events are best effort; the database is the source of truth
            logger.warning("could not publish status of run %s", run_id, exc_info=True)
