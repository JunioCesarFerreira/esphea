"""Use cases of run analyses (API side): create, inspect, delete and read results."""

import logging
import math
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from esphea.experiments.config import ExperimentConfig
from esphea.experiments.registry import ProblemRegistry
from esphea.experiments.storage import SnapshotReader, snapshot_directory
from esphea.messaging.ports import JobKind, JobQueue, JobRef
from esphea.persistence.models import AnalysisRow, RunRow, RunStatus
from esphea.persistence.repositories import AnalysisRepository, RunRepository
from esphea.services.errors import ConflictError, InvalidRequestError, NotFoundError
from esphea.topology.analysis import evenly_spaced
from esphea.topology.clouds import (
    SELECTORS,
    NormalizationKind,
    PointCloudKind,
    build_normalizer,
)
from esphea.topology.config import MAX_POINTS, TOPOLOGY_ANALYSIS, TopologyAnalysisConfig
from esphea.topology.distances import diameter, nearest_neighbour_distances
from esphea.topology.storage import TopologyResultReader, analysis_directory

logger = logging.getLogger(__name__)

SUGGESTION_SAMPLE_GENERATIONS = 50
FINISHED = (RunStatus.COMPLETED, RunStatus.CANCELLED)


@dataclass(frozen=True, slots=True)
class EpsilonSuggestion:
    """Scale statistics of a run's point clouds, to choose ``max_epsilon``."""

    max_diameter: float
    median_diameter: float
    median_nearest_neighbour: float
    suggested_max_epsilon: float


def round_up(value: float, significant: int = 2) -> float:
    if value <= 0:
        return 1.0
    step = 10 ** (math.floor(math.log10(value)) - significant + 1)
    return float(round(math.ceil(value / step - 1e-9) * step, 12))


class AnalysisService:
    def __init__(
        self,
        session: Session,
        *,
        queue: JobQueue,
        problems: ProblemRegistry,
        runs_dir: Path,
    ) -> None:
        self._session = session
        self._runs = RunRepository(session)
        self._analyses = AnalysisRepository(session)
        self._queue = queue
        self._problems = problems
        self._runs_dir = runs_dir

    # --- helpers ----------------------------------------------------------------------

    def _run(self, run_id: uuid.UUID) -> RunRow:
        run = self._runs.get(run_id)
        if run is None:
            raise NotFoundError(f"run {run_id} not found")
        return run

    def _snapshots(self, run: RunRow) -> SnapshotReader:
        if run.status not in FINISHED:
            raise ConflictError("analyses require a finished run")
        try:
            return SnapshotReader(snapshot_directory(self._runs_dir, run.id, run.attempt))
        except FileNotFoundError:
            raise ConflictError("the run has no stored generations") from None

    def _validate(self, run: RunRow, config: TopologyAnalysisConfig) -> None:
        experiment = ExperimentConfig.model_validate(run.experiment.config)
        factor = 2 if config.point_cloud == PointCloudKind.MERGED else 1
        if experiment.pop_size * factor > MAX_POINTS:
            raise InvalidRequestError(
                f"point clouds of {experiment.pop_size * factor} points exceed the limit of "
                f"{MAX_POINTS} for Vietoris-Rips"
            )
        try:
            build_normalizer(config.normalization, self._problems.build(experiment.problem))
        except ValueError as exc:
            raise InvalidRequestError(str(exc)) from None

    # --- commands ---------------------------------------------------------------------

    def create(self, run_id: uuid.UUID, config: TopologyAnalysisConfig) -> AnalysisRow:
        run = self._run(run_id)
        self._snapshots(run)
        self._validate(run, config)
        analysis = self._analyses.add(run.id, TOPOLOGY_ANALYSIS, config.model_dump(mode="json"))
        self._session.commit()
        try:
            self._queue.enqueue(JobRef(JobKind.ANALYSIS, analysis.id, analysis.attempt + 1))
        except Exception:
            logger.exception("could not enqueue analysis %s; the watchdog will retry", analysis.id)
        self._session.refresh(analysis)
        return analysis

    def delete(self, analysis_id: uuid.UUID) -> None:
        analysis = self.get(analysis_id)
        if analysis.status.is_active:
            raise ConflictError("the analysis is still being computed")
        root = analysis_directory(self._runs_dir, analysis.run_id, analysis.id, 0).parent
        self._analyses.delete(analysis)
        self._session.commit()
        shutil.rmtree(root, ignore_errors=True)

    # --- queries ----------------------------------------------------------------------

    def get(self, analysis_id: uuid.UUID) -> AnalysisRow:
        analysis = self._analyses.get(analysis_id)
        if analysis is None:
            raise NotFoundError(f"analysis {analysis_id} not found")
        return analysis

    def list_for_run(self, run_id: uuid.UUID) -> list[AnalysisRow]:
        self._run(run_id)
        return list(self._analyses.list_for_run(run_id))

    def results(self, analysis_id: uuid.UUID) -> TopologyResultReader:
        analysis = self.get(analysis_id)
        if analysis.status != RunStatus.COMPLETED:
            raise ConflictError(f"the analysis is {analysis.status.value}")
        directory = analysis_directory(
            self._runs_dir, analysis.run_id, analysis.id, analysis.attempt
        )
        try:
            return TopologyResultReader(directory)
        except FileNotFoundError:
            raise NotFoundError("the analysis results are missing") from None

    def suggest_epsilon(
        self, run_id: uuid.UUID, point_cloud: PointCloudKind, normalization: NormalizationKind
    ) -> EpsilonSuggestion:
        """Diameters and nearest-neighbour spacing over (up to 50) stored generations."""
        run = self._run(run_id)
        reader = self._snapshots(run)
        experiment = ExperimentConfig.model_validate(run.experiment.config)
        try:
            normalizer = build_normalizer(normalization, self._problems.build(experiment.problem))
        except ValueError as exc:
            raise InvalidRequestError(str(exc)) from None
        sampled = set(evenly_spaced(reader.generations(), SUGGESTION_SAMPLE_GENERATIONS))
        selector = SELECTORS[point_cloud]
        diameters: list[float] = []
        spacings: list[float] = []
        for snapshot in reader.iter_generations():
            if snapshot.generation not in sampled:
                continue
            points = normalizer.transform(selector.select(snapshot))
            diameters.append(diameter(points))
            spacings.append(float(np.median(nearest_neighbour_distances(points))))
        largest = max(diameters)
        return EpsilonSuggestion(
            max_diameter=largest,
            median_diameter=float(np.median(diameters)),
            median_nearest_neighbour=float(np.median(spacings)),
            suggested_max_epsilon=round_up(largest),
        )
