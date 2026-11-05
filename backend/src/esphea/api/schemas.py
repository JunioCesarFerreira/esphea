"""HTTP response models (request bodies reuse :mod:`esphea.experiments.config`)."""

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field

from esphea.experiments.config import (
    AlgorithmConfig,
    DTLZ2Config,
    DTLZ7Config,
    ExperimentConfig,
    MetricsConfig,
    NSGA2Config,
    NSGA3Config,
    ProblemConfig,
    SMSEMOAConfig,
    SnapshotConfig,
    ZDT1Config,
    ZDT3Config,
    ZDT4Config,
)
from esphea.experiments.storage import GenerationSnapshot, SnapshotGroup
from esphea.persistence.models import ExperimentRow, RunRow, RunStatus
from esphea.services.experiments import aggregate_status
from esphea.services.results import IndicatorSummary, MetricSeries


class CatalogOut(BaseModel):
    """Available components with their default parameters."""

    problems: list[ProblemConfig]
    algorithms: list[AlgorithmConfig]
    metrics: MetricsConfig
    snapshots: SnapshotConfig


def default_catalog() -> CatalogOut:
    return CatalogOut(
        problems=[DTLZ2Config(), DTLZ7Config(), ZDT1Config(), ZDT3Config(), ZDT4Config()],
        algorithms=[NSGA2Config(), NSGA3Config(), SMSEMOAConfig()],
        metrics=MetricsConfig(),
        snapshots=SnapshotConfig(),
    )


class ExperimentPreviewOut(BaseModel):
    """Quantities derived from a configuration, shown while it is being edited."""

    n_var: int
    n_obj: int
    pop_size: int
    n_reference_directions: int | None
    estimated_snapshot_bytes_per_run: int
    estimated_snapshot_bytes_total: int

    @classmethod
    def from_config(cls, config: ExperimentConfig) -> Self:
        algorithm = config.algorithm
        per_run = config.estimated_snapshot_bytes()
        return cls(
            n_var=config.problem.n_var,
            n_obj=config.problem.n_obj,
            pop_size=config.pop_size,
            n_reference_directions=algorithm.n_reference_directions(config.problem.n_obj)
            if isinstance(algorithm, NSGA3Config)
            else None,
            estimated_snapshot_bytes_per_run=per_run,
            estimated_snapshot_bytes_total=per_run * config.n_runs,
        )


class RunOut(BaseModel):
    id: uuid.UUID
    index: int
    seed: int
    status: RunStatus
    generation: int
    attempt: int = Field(description="Execution attempt (0 = not started; >1 after recovery).")
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None

    @classmethod
    def from_row(cls, row: RunRow) -> Self:
        return cls(
            id=row.id,
            index=row.index,
            seed=row.seed,
            status=row.status,
            generation=row.generation,
            attempt=row.attempt,
            started_at=row.started_at,
            finished_at=row.finished_at,
            error=row.error,
        )


class ExperimentSummaryOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    status: RunStatus
    progress: float = Field(ge=0, le=1)
    problem: str
    n_obj: int
    algorithm: str
    pop_size: int
    n_gen: int
    n_runs: int
    run_counts: dict[RunStatus, int]

    @classmethod
    def from_row(cls, row: ExperimentRow) -> Self:
        config = ExperimentConfig.model_validate(row.config)
        done = sum(
            config.n_gen if run.status == RunStatus.COMPLETED else min(run.generation, config.n_gen)
            for run in row.runs
        )
        counts = dict.fromkeys(RunStatus, 0)
        for run in row.runs:
            counts[run.status] += 1
        return cls(
            id=row.id,
            name=row.name,
            created_at=row.created_at,
            status=aggregate_status(run.status for run in row.runs),
            progress=done / (config.n_gen * max(len(row.runs), 1)),
            problem=config.problem.name,
            n_obj=config.problem.n_obj,
            algorithm=config.algorithm.name,
            pop_size=config.pop_size,
            n_gen=config.n_gen,
            n_runs=config.n_runs,
            run_counts=counts,
        )


class ExperimentOut(ExperimentSummaryOut):
    config: ExperimentConfig
    runs: list[RunOut]

    @classmethod
    def from_row(cls, row: ExperimentRow) -> Self:
        summary = ExperimentSummaryOut.from_row(row)
        return cls(
            **summary.model_dump(),
            config=ExperimentConfig.model_validate(row.config),
            runs=[RunOut.from_row(run) for run in row.runs],
        )


class MetricSeriesOut(BaseModel):
    generation: list[int]
    n_nondominated: list[int]
    elapsed_seconds: list[float]
    values: dict[str, list[float | None]]

    @classmethod
    def from_series(cls, series: MetricSeries) -> Self:
        return cls(
            generation=series.generation,
            n_nondominated=series.n_nondominated,
            elapsed_seconds=series.elapsed_seconds,
            values=series.values,
        )


class IndicatorSummaryOut(BaseModel):
    generation: list[int]
    median: list[float]
    q1: list[float]
    q3: list[float]
    n_runs: list[int]

    @classmethod
    def from_summary(cls, summary: IndicatorSummary) -> Self:
        return cls(
            generation=summary.generation,
            median=summary.median,
            q1=summary.q1,
            q3=summary.q3,
            n_runs=summary.n_runs,
        )


class StoredGenerationsOut(BaseModel):
    generations: list[int]


class SnapshotGroupOut(BaseModel):
    F: list[list[float]]
    X: list[list[float]] | None
    survived: list[bool]
    rank: list[int] = Field(description="Rank in this generation's survival; -1 if discarded.")
    times_selected: list[int]
    parents: list[list[int]] = Field(description="Indices into the population; -1 if none.")
    mutated: list[bool]

    @classmethod
    def from_group(cls, group: SnapshotGroup) -> Self:
        return cls(
            F=group.F.tolist(),
            X=None if group.X is None else group.X.tolist(),
            survived=group.survived.tolist(),
            rank=group.rank.tolist(),
            times_selected=group.times_selected.tolist(),
            parents=group.parents.tolist(),
            mutated=group.mutated.tolist(),
        )


class GenerationSnapshotOut(BaseModel):
    run_id: uuid.UUID
    generation: int
    population: SnapshotGroupOut
    offspring: SnapshotGroupOut | None

    @classmethod
    def from_snapshot(cls, run_id: uuid.UUID, snapshot: GenerationSnapshot) -> Self:
        return cls(
            run_id=run_id,
            generation=snapshot.generation,
            population=SnapshotGroupOut.from_group(snapshot.population),
            offspring=None
            if snapshot.offspring is None
            else SnapshotGroupOut.from_group(snapshot.offspring),
        )


class ParetoFrontOut(BaseModel):
    points: list[list[float]] | None = Field(description="Null when the front is unknown.")
