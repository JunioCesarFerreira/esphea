"""Read-side use cases: metrics, aggregates, snapshots and reference fronts."""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from esphea.core.problem import KnownParetoFront
from esphea.core.types import FloatArray
from esphea.experiments.config import ExperimentConfig
from esphea.experiments.registry import ProblemRegistry
from esphea.experiments.storage import GenerationSnapshot, SnapshotReader
from esphea.persistence.models import RunRow
from esphea.persistence.repositories import ExperimentRepository, MetricsRepository, RunRepository
from esphea.services.errors import NotFoundError


@dataclass(frozen=True, slots=True)
class MetricSeries:
    generation: list[int] = field(default_factory=list)
    n_nondominated: list[int] = field(default_factory=list)
    elapsed_seconds: list[float] = field(default_factory=list)
    values: dict[str, list[float | None]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IndicatorSummary:
    """Across-run statistics of one indicator, per generation."""

    generation: list[int]
    median: list[float]
    q1: list[float]
    q3: list[float]
    n_runs: list[int]


class ResultsService:
    def __init__(self, session: Session, *, problems: ProblemRegistry, runs_dir: Path) -> None:
        self._experiments = ExperimentRepository(session)
        self._runs = RunRepository(session)
        self._metrics = MetricsRepository(session)
        self._problems = problems
        self._runs_dir = runs_dir

    def _run(self, run_id: uuid.UUID) -> RunRow:
        run = self._runs.get(run_id)
        if run is None:
            raise NotFoundError(f"run {run_id} not found")
        return run

    def run_metrics(self, run_id: uuid.UUID) -> MetricSeries:
        self._run(run_id)
        series = MetricSeries()
        rows = self._metrics.for_runs([run_id])
        names = sorted({name for row in rows for name in row.values})
        for name in names:
            series.values[name] = []
        for row in rows:
            series.generation.append(row.generation)
            series.n_nondominated.append(row.n_nondominated)
            series.elapsed_seconds.append(row.elapsed_seconds)
            for name in names:
                series.values[name].append(row.values.get(name))
        return series

    def experiment_metrics(self, experiment_id: uuid.UUID) -> dict[str, IndicatorSummary]:
        experiment = self._experiments.get(experiment_id)
        if experiment is None:
            raise NotFoundError(f"experiment {experiment_id} not found")
        rows = self._metrics.for_runs([run.id for run in experiment.runs])
        samples: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
        for row in rows:
            for name, value in row.values.items():
                samples[name][row.generation].append(value)
        summaries: dict[str, IndicatorSummary] = {}
        for name, by_generation in sorted(samples.items()):
            generations = sorted(by_generation)
            quartiles = np.array(
                [np.percentile(by_generation[g], [25, 50, 75]) for g in generations]
            ).reshape(-1, 3)
            summaries[name] = IndicatorSummary(
                generation=generations,
                q1=quartiles[:, 0].tolist(),
                median=quartiles[:, 1].tolist(),
                q3=quartiles[:, 2].tolist(),
                n_runs=[len(by_generation[g]) for g in generations],
            )
        return summaries

    def _reader(self, run_id: uuid.UUID) -> SnapshotReader:
        self._run(run_id)
        try:
            return SnapshotReader(self._runs_dir / str(run_id))
        except FileNotFoundError:
            raise NotFoundError(f"run {run_id} has no snapshots") from None

    def stored_generations(self, run_id: uuid.UUID) -> list[int]:
        try:
            return self._reader(run_id).generations()
        except NotFoundError:
            self._run(run_id)  # distinguish "unknown run" from "nothing stored yet"
            return []

    def snapshot(
        self, run_id: uuid.UUID, generation: int, *, decision_variables: bool
    ) -> GenerationSnapshot:
        try:
            return self._reader(run_id).read(generation, decision_variables=decision_variables)
        except KeyError:
            raise NotFoundError(f"generation {generation} is not stored") from None

    def pareto_front(self, experiment_id: uuid.UUID, n_points: int) -> FloatArray | None:
        experiment = self._experiments.get(experiment_id)
        if experiment is None:
            raise NotFoundError(f"experiment {experiment_id} not found")
        config = ExperimentConfig.model_validate(experiment.config)
        problem = self._problems.build(config.problem)
        if not isinstance(problem, KnownParetoFront):
            return None
        return problem.pareto_front(n_points)
