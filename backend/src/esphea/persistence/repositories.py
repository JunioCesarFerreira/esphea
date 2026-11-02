"""Repositories: the only code that issues SQL."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from esphea.experiments.config import ExperimentConfig
from esphea.experiments.observers import GenerationMetrics
from esphea.persistence.models import ExperimentRow, RunMetricRow, RunRow, RunStatus


def _now() -> datetime:
    return datetime.now(UTC)


class ExperimentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, config: ExperimentConfig) -> ExperimentRow:
        experiment = ExperimentRow(name=config.name, config=config.model_dump(mode="json"))
        experiment.runs = [
            RunRow(
                index=index,
                seed=seed,
                status=RunStatus.QUEUED,
                generation=0,
                attempt=0,
                enqueued_at=_now(),
            )
            for index, seed in enumerate(config.run_seeds())
        ]
        self._session.add(experiment)
        self._session.flush()
        return experiment

    def get(self, experiment_id: uuid.UUID) -> ExperimentRow | None:
        statement = (
            select(ExperimentRow)
            .where(ExperimentRow.id == experiment_id)
            .options(selectinload(ExperimentRow.runs))
        )
        return self._session.scalars(statement).one_or_none()

    def list(self) -> Sequence[ExperimentRow]:
        statement = (
            select(ExperimentRow)
            .options(selectinload(ExperimentRow.runs))
            .order_by(ExperimentRow.created_at.desc())
        )
        return self._session.scalars(statement).all()

    def delete(self, experiment: ExperimentRow) -> None:
        self._session.delete(experiment)
        self._session.flush()


class RunRepository:
    """Run state transitions.

    A worker owns a run through its ``attempt`` number: every write made on its
    behalf is conditioned on ``status = running AND attempt = <its attempt>``
    (fencing), so a worker that lost its lease can no longer change the run.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, run_id: uuid.UUID) -> RunRow | None:
        statement = (
            select(RunRow).where(RunRow.id == run_id).options(selectinload(RunRow.experiment))
        )
        return self._session.scalars(statement).one_or_none()

    @staticmethod
    def _owned(run_id: uuid.UUID, attempt: int) -> tuple[ColumnElement[bool], ...]:
        return (RunRow.id == run_id, RunRow.status == RunStatus.RUNNING, RunRow.attempt == attempt)

    def claim(self, run_id: uuid.UUID, attempt: int) -> bool:
        """Atomically start ``attempt`` of a queued run; false if it is not claimable."""
        now = _now()
        result = self._session.execute(
            update(RunRow)
            .where(
                RunRow.id == run_id,
                RunRow.status == RunStatus.QUEUED,
                RunRow.attempt == attempt - 1,
            )
            .values(
                status=RunStatus.RUNNING,
                attempt=attempt,
                started_at=now,
                heartbeat_at=now,
                finished_at=None,
                generation=0,
                error=None,
            )
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def renew_lease(self, run_id: uuid.UUID, attempt: int) -> bool:
        """Refresh the heartbeat; false if the attempt no longer owns the run."""
        result = self._session.execute(
            update(RunRow).where(*self._owned(run_id, attempt)).values(heartbeat_at=_now())
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def lock_owned(self, run_id: uuid.UUID, attempt: int) -> bool:
        """Lock the run row for the transaction if ``attempt`` still owns it.

        Serialises the worker's writes with the watchdog's recovery of the same run.
        """
        statement = select(RunRow.id).where(*self._owned(run_id, attempt)).with_for_update()
        return self._session.scalars(statement).first() is not None

    def set_generation(self, run_id: uuid.UUID, attempt: int, generation: int) -> bool:
        """Record progress; false if the attempt no longer owns the run."""
        result = self._session.execute(
            update(RunRow).where(*self._owned(run_id, attempt)).values(generation=generation)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def finish(
        self,
        run_id: uuid.UUID,
        attempt: int,
        status: RunStatus,
        *,
        generation: int | None = None,
        error: str | None = None,
    ) -> bool:
        """End ``attempt`` with ``status``; false if the attempt no longer owns the run."""
        values: dict[str, object] = {"status": status, "finished_at": _now(), "error": error}
        if generation is not None:
            values["generation"] = generation
        result = self._session.execute(
            update(RunRow).where(*self._owned(run_id, attempt)).values(**values)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def cancel_queued(self, experiment_id: uuid.UUID) -> list[tuple[uuid.UUID, int]]:
        """Cancel the runs that have not started; return their ids and attempts."""
        result = self._session.execute(
            update(RunRow)
            .where(RunRow.experiment_id == experiment_id, RunRow.status == RunStatus.QUEUED)
            .values(status=RunStatus.CANCELLED, finished_at=_now())
            .returning(RunRow.id, RunRow.attempt)
        )
        return [(run_id, attempt) for run_id, attempt in result]

    def running_ids(self, experiment_id: uuid.UUID) -> list[uuid.UUID]:
        statement = select(RunRow.id).where(
            RunRow.experiment_id == experiment_id, RunRow.status == RunStatus.RUNNING
        )
        return list(self._session.scalars(statement))

    # --- recovery ---------------------------------------------------------------------

    def lock_stale_running(self, cutoff: datetime) -> Sequence[RunRow]:
        """Running runs whose lease expired before ``cutoff`` (locked, skipping busy rows)."""
        statement = (
            select(RunRow)
            .where(
                RunRow.status == RunStatus.RUNNING,
                func.coalesce(RunRow.heartbeat_at, RunRow.started_at) < cutoff,
            )
            .with_for_update(skip_locked=True)
        )
        return self._session.scalars(statement).all()

    def lock_queued_before(self, cutoff: datetime) -> Sequence[RunRow]:
        """Queued runs enqueued before ``cutoff`` (locked, skipping busy rows)."""
        statement = (
            select(RunRow)
            .where(
                RunRow.status == RunStatus.QUEUED,
                func.coalesce(RunRow.enqueued_at, RunRow.started_at) < cutoff,
            )
            .with_for_update(skip_locked=True)
        )
        return self._session.scalars(statement).all()

    def requeue(self, run: RunRow, note: str) -> None:
        """Put a run whose worker was lost back in the queue (attempt counter is kept)."""
        run.status = RunStatus.QUEUED
        run.generation = 0
        run.started_at = None
        run.heartbeat_at = None
        run.finished_at = None
        run.enqueued_at = _now()
        run.error = note

    def mark_enqueued(self, run: RunRow) -> None:
        run.enqueued_at = _now()

    def fail(self, run: RunRow, error: str) -> None:
        run.status = RunStatus.FAILED
        run.finished_at = _now()
        run.heartbeat_at = None
        run.error = error


class MetricsRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_many(self, run_id: uuid.UUID, rows: Sequence[GenerationMetrics]) -> None:
        self._session.add_all(
            RunMetricRow(
                run_id=run_id,
                generation=row.generation,
                n_nondominated=row.n_nondominated,
                elapsed_seconds=row.elapsed_seconds,
                values=row.values,
            )
            for row in rows
        )
        self._session.flush()

    def delete_for_run(self, run_id: uuid.UUID) -> None:
        self._session.execute(delete(RunMetricRow).where(RunMetricRow.run_id == run_id))

    def for_runs(self, run_ids: Sequence[uuid.UUID]) -> Sequence[RunMetricRow]:
        statement = (
            select(RunMetricRow)
            .where(RunMetricRow.run_id.in_(run_ids))
            .order_by(RunMetricRow.run_id, RunMetricRow.generation)
        )
        return self._session.scalars(statement).all()
