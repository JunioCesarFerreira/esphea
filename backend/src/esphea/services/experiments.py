"""Use cases that change experiments: create, cancel, delete."""

import logging
import shutil
import uuid
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy.orm import Session

from esphea.experiments.config import ExperimentConfig
from esphea.messaging.events import run_status_event
from esphea.messaging.ports import CancellationFlags, EventPublisher, JobQueue
from esphea.persistence.models import ExperimentRow, RunStatus
from esphea.persistence.repositories import ExperimentRepository, RunRepository
from esphea.services.errors import ConflictError, NotFoundError

logger = logging.getLogger(__name__)


def aggregate_status(statuses: Iterable[RunStatus]) -> RunStatus:
    """Single status summarising the runs of an experiment."""
    present = set(statuses)
    for status in (
        RunStatus.RUNNING,
        RunStatus.QUEUED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
    ):
        if status in present:
            return status
    return RunStatus.COMPLETED


class ExperimentService:
    def __init__(
        self,
        session: Session,
        *,
        queue: JobQueue,
        cancellation: CancellationFlags,
        publisher: EventPublisher,
        runs_dir: Path,
    ) -> None:
        self._session = session
        self._experiments = ExperimentRepository(session)
        self._runs = RunRepository(session)
        self._queue = queue
        self._cancellation = cancellation
        self._publisher = publisher
        self._runs_dir = runs_dir

    def get(self, experiment_id: uuid.UUID) -> ExperimentRow:
        experiment = self._experiments.get(experiment_id)
        if experiment is None:
            raise NotFoundError(f"experiment {experiment_id} not found")
        return experiment

    def create(self, config: ExperimentConfig) -> ExperimentRow:
        experiment = self._experiments.add(config)
        self._session.commit()
        # Enqueue only after commit, so workers always find the rows.
        # A failed enqueue is retried by the watchdog, which re-enqueues queued runs
        # whose job is missing from the queue.
        for run in experiment.runs:
            try:
                self._queue.enqueue_run(run.id, run.attempt + 1)
            except Exception:
                logger.exception("could not enqueue run %s; the watchdog will retry", run.id)
        self._session.refresh(experiment)
        return experiment

    def cancel(self, experiment_id: uuid.UUID) -> ExperimentRow:
        experiment = self.get(experiment_id)
        cancelled = self._runs.cancel_queued(experiment_id)
        running = self._runs.running_ids(experiment_id)
        self._session.commit()
        for run_id, attempt in cancelled:
            self._queue.cancel_run(run_id, attempt + 1)
            self._publisher.publish(
                experiment_id,
                run_status_event(experiment_id, run_id, RunStatus.CANCELLED, attempt=attempt),
            )
        for run_id in running:
            self._cancellation.request(run_id)
        self._session.refresh(experiment)
        return experiment

    def delete(self, experiment_id: uuid.UUID) -> None:
        experiment = self.get(experiment_id)
        if any(run.status.is_active for run in experiment.runs):
            raise ConflictError("cancel the experiment before deleting it")
        run_dirs = [self._runs_dir / str(run.id) for run in experiment.runs]
        self._experiments.delete(experiment)
        self._session.commit()
        for directory in run_dirs:
            shutil.rmtree(directory, ignore_errors=True)
