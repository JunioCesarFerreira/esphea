"""Repositories: the only code that issues SQL."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update
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
            RunRow(index=index, seed=seed, status=RunStatus.QUEUED, generation=0)
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
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, run_id: uuid.UUID) -> RunRow | None:
        statement = (
            select(RunRow).where(RunRow.id == run_id).options(selectinload(RunRow.experiment))
        )
        return self._session.scalars(statement).one_or_none()

    def claim(self, run_id: uuid.UUID) -> bool:
        """Atomically move a queued run to running; false if someone else got it."""
        result = self._session.execute(
            update(RunRow)
            .where(RunRow.id == run_id, RunRow.status == RunStatus.QUEUED)
            .values(status=RunStatus.RUNNING, started_at=_now(), generation=0, error=None)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    def set_generation(self, run_id: uuid.UUID, generation: int) -> None:
        self._session.execute(
            update(RunRow).where(RunRow.id == run_id).values(generation=generation)
        )

    def finish(
        self,
        run_id: uuid.UUID,
        status: RunStatus,
        *,
        generation: int | None = None,
        error: str | None = None,
    ) -> None:
        values: dict[str, object] = {"status": status, "finished_at": _now(), "error": error}
        if generation is not None:
            values["generation"] = generation
        self._session.execute(update(RunRow).where(RunRow.id == run_id).values(**values))

    def cancel_queued(self, experiment_id: uuid.UUID) -> list[uuid.UUID]:
        """Cancel the runs that have not started; return their ids."""
        result = self._session.execute(
            update(RunRow)
            .where(RunRow.experiment_id == experiment_id, RunRow.status == RunStatus.QUEUED)
            .values(status=RunStatus.CANCELLED, finished_at=_now())
            .returning(RunRow.id)
        )
        return list(result.scalars())

    def running_ids(self, experiment_id: uuid.UUID) -> list[uuid.UUID]:
        statement = select(RunRow.id).where(
            RunRow.experiment_id == experiment_id, RunRow.status == RunStatus.RUNNING
        )
        return list(self._session.scalars(statement))


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

    def for_runs(self, run_ids: Sequence[uuid.UUID]) -> Sequence[RunMetricRow]:
        statement = (
            select(RunMetricRow)
            .where(RunMetricRow.run_id.in_(run_ids))
            .order_by(RunMetricRow.run_id, RunMetricRow.generation)
        )
        return self._session.scalars(statement).all()
