"""Repositories: the only code that issues SQL."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from esphea.experiments.config import ExperimentConfig
from esphea.experiments.observers import GenerationMetrics
from esphea.persistence.models import (
    AnalysisRow,
    ExperimentRow,
    LeasedJob,
    RunMetricRow,
    RunRow,
    RunStatus,
)


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


class LeasedJobRepository[J: LeasedJob]:
    """State transitions shared by every job executed under a lease.

    A worker owns a job through its ``attempt`` number: every write made on its
    behalf is conditioned on ``status = running AND attempt = <its attempt>``
    (fencing), so a worker that lost its lease can no longer change the job.
    """

    model: type[J]

    def __init__(self, session: Session) -> None:
        self._session = session

    def _owned(self, job_id: uuid.UUID, attempt: int) -> tuple[ColumnElement[bool], ...]:
        model = self.model
        return (model.id == job_id, model.status == RunStatus.RUNNING, model.attempt == attempt)

    def _claim_values(self) -> dict[str, object]:
        """Extra columns reset when an attempt starts."""
        return {}

    def _reset(self, job: J) -> None:
        """Extra columns reset when a job is queued again."""

    def claim(self, job_id: uuid.UUID, attempt: int) -> bool:
        """Atomically start ``attempt`` of a queued job; false if it is not claimable."""
        model = self.model
        now = _now()
        result = self._session.execute(
            update(model)
            .where(
                model.id == job_id, model.status == RunStatus.QUEUED, model.attempt == attempt - 1
            )
            .values(
                status=RunStatus.RUNNING,
                attempt=attempt,
                started_at=now,
                heartbeat_at=now,
                finished_at=None,
                error=None,
                **self._claim_values(),
            )
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def renew_lease(self, job_id: uuid.UUID, attempt: int) -> bool:
        """Refresh the heartbeat; false if the attempt no longer owns the job."""
        result = self._session.execute(
            update(self.model).where(*self._owned(job_id, attempt)).values(heartbeat_at=_now())
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def lock_owned(self, job_id: uuid.UUID, attempt: int) -> bool:
        """Lock the job row for the transaction if ``attempt`` still owns it.

        Serialises the worker's writes with the watchdog's recovery of the same job.
        """
        statement = select(self.model.id).where(*self._owned(job_id, attempt)).with_for_update()
        return self._session.scalars(statement).first() is not None

    def _update_owned(self, job_id: uuid.UUID, attempt: int, **values: object) -> bool:
        result = self._session.execute(
            update(self.model).where(*self._owned(job_id, attempt)).values(**values)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def _finish(
        self,
        job_id: uuid.UUID,
        attempt: int,
        status: RunStatus,
        error: str | None,
        **values: object,
    ) -> bool:
        return self._update_owned(
            job_id, attempt, status=status, finished_at=_now(), error=error, **values
        )

    # --- recovery ---------------------------------------------------------------------

    def lock_stale_running(self, cutoff: datetime) -> Sequence[J]:
        """Running jobs whose lease expired before ``cutoff`` (locked, skipping busy rows)."""
        model = self.model
        statement = (
            select(model)
            .where(
                model.status == RunStatus.RUNNING,
                func.coalesce(model.heartbeat_at, model.started_at) < cutoff,
            )
            .with_for_update(skip_locked=True)
        )
        return self._session.scalars(statement).all()

    def lock_queued_before(self, cutoff: datetime) -> Sequence[J]:
        """Queued jobs enqueued before ``cutoff`` (locked, skipping busy rows)."""
        model = self.model
        statement = (
            select(model)
            .where(
                model.status == RunStatus.QUEUED,
                func.coalesce(model.enqueued_at, model.started_at) < cutoff,
            )
            .with_for_update(skip_locked=True)
        )
        return self._session.scalars(statement).all()

    def requeue(self, job: J, note: str) -> None:
        """Put a job whose worker was lost back in the queue (attempt counter is kept)."""
        job.status = RunStatus.QUEUED
        job.started_at = None
        job.heartbeat_at = None
        job.finished_at = None
        job.enqueued_at = _now()
        job.error = note
        self._reset(job)

    def mark_enqueued(self, job: J) -> None:
        job.enqueued_at = _now()

    def fail(self, job: J, error: str) -> None:
        job.status = RunStatus.FAILED
        job.finished_at = _now()
        job.heartbeat_at = None
        job.error = error


class RunRepository(LeasedJobRepository[RunRow]):
    model = RunRow

    def get(self, run_id: uuid.UUID) -> RunRow | None:
        statement = (
            select(RunRow).where(RunRow.id == run_id).options(selectinload(RunRow.experiment))
        )
        return self._session.scalars(statement).one_or_none()

    def _claim_values(self) -> dict[str, object]:
        return {"generation": 0}

    def _reset(self, job: RunRow) -> None:
        job.generation = 0

    def set_generation(self, run_id: uuid.UUID, attempt: int, generation: int) -> bool:
        """Record progress; false if the attempt no longer owns the run."""
        return self._update_owned(run_id, attempt, generation=generation)

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
        extra: dict[str, object] = {} if generation is None else {"generation": generation}
        return self._finish(run_id, attempt, status, error, **extra)

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


class AnalysisRepository(LeasedJobRepository[AnalysisRow]):
    model = AnalysisRow

    def add(
        self,
        run_id: uuid.UUID,
        kind: str,
        config: dict[str, Any],
        *,
        batch_id: uuid.UUID | None = None,
    ) -> AnalysisRow:
        analysis = AnalysisRow(
            run_id=run_id,
            batch_id=batch_id,
            kind=kind,
            config=config,
            status=RunStatus.QUEUED,
            attempt=0,
            progress=0,
            total=0,
            enqueued_at=_now(),
        )
        self._session.add(analysis)
        self._session.flush()
        return analysis

    def get(self, analysis_id: uuid.UUID) -> AnalysisRow | None:
        statement = (
            select(AnalysisRow)
            .where(AnalysisRow.id == analysis_id)
            .options(selectinload(AnalysisRow.run).selectinload(RunRow.experiment))
        )
        return self._session.scalars(statement).one_or_none()

    def list_for_run(self, run_id: uuid.UUID) -> Sequence[AnalysisRow]:
        statement = (
            select(AnalysisRow)
            .where(AnalysisRow.run_id == run_id)
            .order_by(AnalysisRow.created_at.desc())
        )
        return self._session.scalars(statement).all()

    def list_for_experiment(self, experiment_id: uuid.UUID) -> Sequence[AnalysisRow]:
        statement = (
            select(AnalysisRow)
            .join(RunRow, AnalysisRow.run_id == RunRow.id)
            .where(RunRow.experiment_id == experiment_id)
            .options(selectinload(AnalysisRow.run))
            .order_by(AnalysisRow.created_at.desc(), RunRow.index)
        )
        return self._session.scalars(statement).all()

    def list_batch(self, batch_id: uuid.UUID) -> Sequence[AnalysisRow]:
        statement = (
            select(AnalysisRow)
            .join(RunRow, AnalysisRow.run_id == RunRow.id)
            .where(AnalysisRow.batch_id == batch_id)
            .options(selectinload(AnalysisRow.run))
            .order_by(RunRow.index)
        )
        return self._session.scalars(statement).all()

    def _claim_values(self) -> dict[str, object]:
        return {"progress": 0}

    def _reset(self, job: AnalysisRow) -> None:
        job.progress = 0

    def set_progress(self, analysis_id: uuid.UUID, attempt: int, done: int, total: int) -> bool:
        return self._update_owned(analysis_id, attempt, progress=done, total=total)

    def finish(
        self, analysis_id: uuid.UUID, attempt: int, status: RunStatus, *, error: str | None = None
    ) -> bool:
        return self._finish(analysis_id, attempt, status, error)

    def delete(self, analysis: AnalysisRow) -> None:
        self._session.delete(analysis)
        self._session.flush()


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
