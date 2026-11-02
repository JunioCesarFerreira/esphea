"""Worker-side use case: execute one run and record everything about it."""

import logging
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from esphea.experiments.config import ExperimentConfig
from esphea.experiments.observers import GenerationMetrics, RunProgress
from esphea.experiments.runner import RunExecutor
from esphea.messaging.events import run_progress_event, run_status_event
from esphea.messaging.ports import CancellationFlags, EventPublisher
from esphea.persistence.models import RunStatus
from esphea.persistence.repositories import MetricsRepository, RunRepository

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 4000


class DatabaseMetricsSink:
    """Buffers metric rows and writes them in batches (by size or age)."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        run_id: uuid.UUID,
        *,
        max_rows: int = 200,
        max_age_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions = sessions
        self._run_id = run_id
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
    ) -> None:
        self._sessions = sessions
        self._publisher = publisher
        self._experiment_id = experiment_id
        self._run_id = run_id

    def report(self, progress: RunProgress) -> None:
        with self._sessions.begin() as session:
            RunRepository(session).set_generation(self._run_id, progress.generation)
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
        cancellation_poll_seconds: float = 0.5,
    ) -> None:
        self._sessions = sessions
        self._executor = executor
        self._publisher = publisher
        self._cancellation = cancellation
        self._runs_dir = runs_dir
        self._poll = cancellation_poll_seconds

    def execute(self, run_id: uuid.UUID) -> RunStatus | None:
        """Run ``run_id`` if it is still queued; return its final status (None if skipped)."""
        with self._sessions.begin() as session:
            runs = RunRepository(session)
            run = runs.get(run_id)
            if run is None or not runs.claim(run_id):
                logger.info("run %s is not queued anymore; skipping", run_id)
                return None
            experiment_id = run.experiment_id
            seed = run.seed
            config = ExperimentConfig.model_validate(run.experiment.config)

        self._publish_status(experiment_id, run_id, RunStatus.RUNNING, generation=0)
        try:
            outcome = self._executor.execute(
                config,
                seed,
                metrics_sink=DatabaseMetricsSink(self._sessions, run_id),
                progress=ProgressBridge(
                    self._sessions, self._publisher, experiment_id=experiment_id, run_id=run_id
                ),
                snapshot_dir=self._runs_dir / str(run_id),
                should_cancel=ThrottledCheck(
                    lambda: self._cancellation.is_requested(run_id), self._poll
                ),
            )
        except Exception as exc:
            logger.exception("run %s failed", run_id)
            error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]
            self._finish(experiment_id, run_id, RunStatus.FAILED, error=error)
            return RunStatus.FAILED
        finally:
            self._cancellation.clear(run_id)

        status = RunStatus.CANCELLED if outcome.cancelled else RunStatus.COMPLETED
        self._finish(experiment_id, run_id, status, generation=outcome.generations)
        return status

    def _finish(
        self,
        experiment_id: uuid.UUID,
        run_id: uuid.UUID,
        status: RunStatus,
        *,
        generation: int | None = None,
        error: str | None = None,
    ) -> None:
        with self._sessions.begin() as session:
            RunRepository(session).finish(run_id, status, generation=generation, error=error)
        self._publish_status(experiment_id, run_id, status, generation=generation, error=error)

    def _publish_status(
        self,
        experiment_id: uuid.UUID,
        run_id: uuid.UUID,
        status: RunStatus,
        *,
        generation: int | None = None,
        error: str | None = None,
    ) -> None:
        try:
            self._publisher.publish(
                experiment_id,
                run_status_event(experiment_id, run_id, status, generation=generation, error=error),
            )
        except Exception:  # events are best effort; the database is the source of truth
            logger.warning("could not publish status of run %s", run_id, exc_info=True)
