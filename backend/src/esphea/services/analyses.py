"""Use cases of run analyses (API side): create, inspect, delete and read results."""

import logging
import math
import shutil
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sqlalchemy.orm import Session

from esphea.core.types import FloatArray, IntArray
from esphea.experiments.config import ExperimentConfig
from esphea.experiments.registry import ProblemRegistry
from esphea.experiments.storage import SnapshotReader, snapshot_directory
from esphea.messaging.ports import JobKind, JobQueue, JobRef
from esphea.persistence.models import AnalysisRow, RunRow, RunStatus
from esphea.persistence.repositories import (
    AnalysisRepository,
    ExperimentRepository,
    RunRepository,
)
from esphea.services.errors import ConflictError, InvalidRequestError, NotFoundError
from esphea.topology.analysis import evenly_spaced
from esphea.topology.clouds import (
    SELECTORS,
    NormalizationKind,
    PointCloudKind,
    build_normalizer,
)
from esphea.topology.config import (
    TOPOLOGY_ANALYSIS,
    ZIGZAG_ANALYSIS,
    TopologyAnalysisConfig,
    ZigzagAnalysisConfig,
)
from esphea.topology.distances import diameter, nearest_neighbour_distances
from esphea.topology.runners import AnalysisContext, AnalysisRunner, default_runners
from esphea.topology.storage import TopologyResultReader, analysis_directory
from esphea.topology.zigzag import epsilon_components, is_r_step, step_generation
from esphea.topology.zigzag_storage import ZigzagResultReader

logger = logging.getLogger(__name__)

type AnalysisConfigModel = TopologyAnalysisConfig | ZigzagAnalysisConfig

SUGGESTION_SAMPLE_GENERATIONS = 50
ZIGZAG_SCALE_FACTORS = (1.0, 1.5, 2.0)
"""Suggested zigzag scales, as multiples of the median nearest-neighbour spacing."""
FINISHED = (RunStatus.COMPLETED, RunStatus.CANCELLED)


@dataclass(frozen=True, slots=True)
class EpsilonSuggestion:
    """Scale statistics of a run's point clouds, to choose epsilon values."""

    max_diameter: float
    median_diameter: float
    median_nearest_neighbour: float
    suggested_max_epsilon: float
    suggested_scales: list[float]


@dataclass(frozen=True, slots=True)
class RepresentativeView:
    """A zigzag bar at one step: the population there and the representative cycle."""

    step: int
    generation: int
    is_r_step: bool
    dimension: int
    members: IntArray
    points: FloatArray  # objective vectors of ``members`` (as analysed)
    simplices: list[list[int]] | None  # None: no representative available
    component: IntArray  # H0: individuals of the represented niche(s); empty otherwise


@dataclass(frozen=True, slots=True)
class Quartiles:
    q1: FloatArray
    median: FloatArray
    q3: FloatArray


@dataclass(frozen=True, slots=True)
class ZigzagBatchSummary:
    """Across-run statistics of a zigzag batch, per generation."""

    generations: list[int]
    n_runs: int
    series: dict[str, Quartiles]


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
        runners: Mapping[str, AnalysisRunner] | None = None,
    ) -> None:
        self._session = session
        self._experiments = ExperimentRepository(session)
        self._runs = RunRepository(session)
        self._analyses = AnalysisRepository(session)
        self._queue = queue
        self._problems = problems
        self._runs_dir = runs_dir
        self._runners = dict(runners or default_runners())

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

    def _context(self, run: RunRow) -> AnalysisContext:
        experiment = ExperimentConfig.model_validate(run.experiment.config)
        return AnalysisContext(
            snapshots=self._snapshots(run),
            problem=self._problems.build(experiment.problem),
            population_size=experiment.pop_size,
        )

    def _validate(self, run: RunRow, config: AnalysisConfigModel) -> None:
        try:
            self._runners[config.kind].validate(config, self._context(run))
        except ValueError as exc:
            raise InvalidRequestError(str(exc)) from None

    def _enqueue(self, analysis: AnalysisRow) -> None:
        try:
            self._queue.enqueue(JobRef(JobKind.ANALYSIS, analysis.id, analysis.attempt + 1))
        except Exception:
            logger.exception("could not enqueue analysis %s; the watchdog will retry", analysis.id)

    @staticmethod
    def _stored_config(config: AnalysisConfigModel) -> dict[str, object]:
        return config.model_dump(mode="json", exclude={"kind"})

    # --- commands ---------------------------------------------------------------------

    def create(self, run_id: uuid.UUID, config: AnalysisConfigModel) -> AnalysisRow:
        run = self._run(run_id)
        self._validate(run, config)
        analysis = self._analyses.add(run.id, config.kind, self._stored_config(config))
        self._session.commit()
        self._enqueue(analysis)
        self._session.refresh(analysis)
        return analysis

    def create_batch(
        self, experiment_id: uuid.UUID, config: AnalysisConfigModel
    ) -> list[AnalysisRow]:
        """One analysis per finished run of an experiment, sharing a batch id."""
        experiment = self._experiments.get(experiment_id)
        if experiment is None:
            raise NotFoundError(f"experiment {experiment_id} not found")
        runs = [run for run in experiment.runs if run.status in FINISHED]
        if not runs:
            raise ConflictError("the experiment has no finished runs")
        for run in runs:
            self._validate(run, config)
        batch_id = uuid.uuid4()
        analyses = [
            self._analyses.add(run.id, config.kind, self._stored_config(config), batch_id=batch_id)
            for run in runs
        ]
        self._session.commit()
        for analysis in analyses:
            self._enqueue(analysis)
            self._session.refresh(analysis)
        return analyses

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

    def list_for_experiment(self, experiment_id: uuid.UUID) -> list[AnalysisRow]:
        if self._experiments.get(experiment_id) is None:
            raise NotFoundError(f"experiment {experiment_id} not found")
        return list(self._analyses.list_for_experiment(experiment_id))

    def _directory(self, analysis: AnalysisRow, kind: str) -> Path:
        if analysis.kind != kind:
            raise ConflictError(f"this is a {analysis.kind} analysis, not a {kind} analysis")
        if analysis.status != RunStatus.COMPLETED:
            raise ConflictError(f"the analysis is {analysis.status.value}")
        return analysis_directory(self._runs_dir, analysis.run_id, analysis.id, analysis.attempt)

    def results(self, analysis_id: uuid.UUID) -> TopologyResultReader:
        try:
            return TopologyResultReader(self._directory(self.get(analysis_id), TOPOLOGY_ANALYSIS))
        except FileNotFoundError:
            raise NotFoundError("the analysis results are missing") from None

    def zigzag_results(self, analysis_id: uuid.UUID) -> ZigzagResultReader:
        try:
            return ZigzagResultReader(self._directory(self.get(analysis_id), ZIGZAG_ANALYSIS))
        except FileNotFoundError:
            raise NotFoundError("the analysis results are missing") from None

    def zigzag_representative(
        self, analysis_id: uuid.UUID, epsilon_index: int, bar: int, step: int
    ) -> RepresentativeView:
        reader = self.zigzag_results(analysis_id)
        try:
            row = reader.bar(epsilon_index, bar)
            epsilon = reader.epsilons[epsilon_index]
        except (KeyError, IndexError) as exc:
            raise NotFoundError(str(exc)) from None
        if not row["birth"] <= step < row["death"]:
            raise InvalidRequestError(f"bar {bar} is not alive at step {step}")
        first, last, points = reader.individuals()
        members = np.flatnonzero((first <= step) & (last >= step))
        simplices = reader.representative(epsilon_index, bar, step)
        component = np.empty(0, dtype=np.intp)
        if simplices and row["dimension"] == 0:
            seeds = {v for simplex in simplices for v in simplex}
            component = epsilon_components(points, members, epsilon, seeds)
        return RepresentativeView(
            step=step,
            generation=step_generation(step),
            is_r_step=is_r_step(step),
            dimension=int(row["dimension"]),
            members=members,
            points=points[members],
            simplices=simplices or None,
            component=component,
        )

    def zigzag_batch_summary(
        self, batch_id: uuid.UUID, epsilon_index: int, dimension: int
    ) -> ZigzagBatchSummary:
        """Median and quartiles across runs of the zigzag events and Betti numbers."""
        analyses = [
            a
            for a in self._analyses.list_batch(batch_id)
            if a.kind == ZIGZAG_ANALYSIS and a.status == RunStatus.COMPLETED
        ]
        if not analyses:
            raise NotFoundError(f"no completed zigzag analysis in batch {batch_id}")
        samples: dict[str, list[np.ndarray]] = {}
        length = None
        for analysis in analyses:
            reader = self.zigzag_results(analysis.id)
            try:
                events = reader.events(epsilon_index, dimension)
                betti = reader.betti(epsilon_index, dimension)
            except KeyError as exc:
                raise NotFoundError(str(exc.args[0])) from None
            series = {
                "betti": betti[0::2].astype(float),  # at P_0, P_1, ..., P_T
                "births_variation": events.births_variation.astype(float),
                "births_selection": events.births_selection.astype(float),
                "deaths_variation": events.deaths_variation.astype(float),
                "deaths_selection": events.deaths_selection.astype(float),
            }
            length = min(length or reader.n_generations + 1, reader.n_generations + 1)
            for name, values in series.items():
                samples.setdefault(name, []).append(values)
        assert length is not None
        quartiles = {}
        for name, runs in samples.items():
            stacked = np.vstack([values[:length] for values in runs])
            q1, median, q3 = np.percentile(stacked, [25, 50, 75], axis=0)
            quartiles[name] = Quartiles(q1=q1, median=median, q3=q3)
        return ZigzagBatchSummary(
            generations=list(range(length)), n_runs=len(analyses), series=quartiles
        )

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
        spacing = float(np.median(spacings))
        return EpsilonSuggestion(
            max_diameter=largest,
            median_diameter=float(np.median(diameters)),
            median_nearest_neighbour=spacing,
            suggested_max_epsilon=round_up(largest),
            suggested_scales=sorted({round_up(spacing * f) for f in ZIGZAG_SCALE_FACTORS}),
        )
