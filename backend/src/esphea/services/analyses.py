"""Use cases of run analyses (API side): create, inspect, delete and read results."""

import hashlib
import json
import logging
import math
import shutil
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from esphea.core.types import BoolArray, FloatArray, IntArray
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
    parse_analysis_config,
)
from esphea.topology.distances import diameter, nearest_neighbour_distances
from esphea.topology.runners import AnalysisContext, AnalysisRunner, default_runners
from esphea.topology.storage import TopologyResultReader, analysis_directory
from esphea.topology.trackers import (
    MethodSummary,
    Resolution,
    TrackerMethod,
    compare_with_zigzag,
    matched,
)
from esphea.topology.zigzag import (
    complex_members,
    epsilon_components,
    is_r_step,
    step_generation,
)
from esphea.topology.zigzag_storage import ZigzagResultReader

logger = logging.getLogger(__name__)

type AnalysisConfigModel = TopologyAnalysisConfig | ZigzagAnalysisConfig

SUGGESTION_SAMPLE_GENERATIONS = 50
ZIGZAG_SCALE_FACTORS = (1.0, 1.5, 2.0)
"""Suggested zigzag scales, as multiples of the population's nearest-neighbour spacing.

The spacing of the survivors P_t is used, not that of R_t: offspring are usually
much closer to their parents than individuals to each other, and that spacing
would make every individual its own component."""
FINISHED = (RunStatus.COMPLETED, RunStatus.CANCELLED)
GROUP_IGNORED_SETTINGS = frozenset({"distance_matrix", "representatives"})
"""Settings that change what is stored but not the summarised series: analyses
differing only in them belong to the same group."""
GROUP_LATER_DEFAULTS = {"middle": "rips"}
"""Settings added after group keys were in use: left out of the key at their default,
so that the keys of earlier analyses do not change."""
BATCH_SERIES = (
    "betti",
    "births_variation",
    "births_selection",
    "deaths_variation",
    "deaths_selection",
)
ZIGZAG_EVENT_SERIES = (
    "births_variation",
    "births_selection",
    "births",
    "deaths_variation",
    "deaths_selection",
    "deaths",
)


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


@dataclass(frozen=True, slots=True)
class Spread:
    q1: float
    median: float
    q3: float


@dataclass(frozen=True, slots=True)
class AnalysisGroup:
    """Analyses of an experiment's runs sharing one configuration.

    ``completed`` keeps the newest completed analysis of each run, in run order;
    ``pending`` counts the runs whose analysis is still queued or running.
    """

    key: str
    kind: str
    config: dict[str, Any]
    completed: list[AnalysisRow]
    pending: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class GroupSummary:
    """Across-run statistics of an analysis group, per generation.

    A run contributes to the generations it has; ``totals`` holds the spread of
    the per-run sums of the event series (zigzag births and deaths).
    """

    kind: str
    generations: list[int]
    n_runs: list[int]
    series: dict[str, Quartiles]
    totals: dict[str, Spread]


type RunSeries = tuple[Sequence[int], Mapping[str, FloatArray]]

TRACKERS_MISSING = "this zigzag analysis predates the niche trackers; run it again to compute them"
TRACKER_RUN_FIELDS = (
    "n_bars",
    "n_long",
    "median_lifetime",
    "p90_lifetime",
    "agreement_step",
    "agreement_generation",
    "long_agreement_step",
    "long_agreement_generation",
)


@dataclass(frozen=True, slots=True)
class TrackerBarsView:
    """``H_0`` bars of a niche tracker and whether the zigzag has the same bar."""

    epsilon: float
    method: TrackerMethod
    n_generations: int
    n_steps: int
    bars: IntArray  # rows (birth, death)
    matched_step: BoolArray
    matched_generation: BoolArray


@dataclass(frozen=True, slots=True)
class TrackerComparison:
    """The zigzag ``H_0`` barcode and the trackers' barcodes of one run, side by side."""

    epsilon: float
    n_generations: int
    n_steps: int
    long_lifetime: int
    methods: list[MethodSummary]


@dataclass(frozen=True, slots=True)
class TrackerRuns:
    """Per-run values of every method (runs whose analysis lacks the trackers are skipped)."""

    epsilon: float
    long_lifetime: int
    n_runs: int
    skipped: int
    methods: dict[str, dict[str, list[float | None]]]  # method -> field -> one value per run


def group_key(kind: str, config: Mapping[str, Any]) -> str:
    """Identifier of the analyses that produce comparable series."""
    settings = parse_analysis_config(kind, dict(config)).model_dump(
        mode="json", exclude={"kind", *GROUP_IGNORED_SETTINGS}
    )
    for name, default in GROUP_LATER_DEFAULTS.items():
        if settings.get(name) == default:
            del settings[name]
    canonical = json.dumps({"kind": kind, **settings}, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _quartiles(values: FloatArray) -> Quartiles:
    """Column-wise quartiles ignoring NaN; NaN where a column has no value."""
    result = np.full((3, values.shape[1]), np.nan)
    valid = ~np.all(np.isnan(values), axis=0)
    if valid.any():
        result[:, valid] = np.nanpercentile(values[:, valid], [25, 50, 75], axis=0)
    return Quartiles(q1=result[0], median=result[1], q3=result[2])


def summarize_runs(runs: Sequence[RunSeries]) -> tuple[list[int], list[int], dict[str, Quartiles]]:
    """Generations, runs per generation and quartiles of every series across ``runs``."""
    generations = sorted({g for run_generations, _ in runs for g in run_generations})
    column = {g: i for i, g in enumerate(generations)}
    n_runs = np.zeros(len(generations), dtype=np.intp)
    stacked: dict[str, FloatArray] = {}
    for row, (run_generations, series) in enumerate(runs):
        columns = [column[g] for g in run_generations]
        n_runs[columns] += 1
        for name, values in series.items():
            if name not in stacked:
                stacked[name] = np.full((len(runs), len(generations)), np.nan)
            stacked[name][row, columns] = values
    quartiles = {name: _quartiles(values) for name, values in stacked.items()}
    return generations, n_runs.tolist(), quartiles


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
        members = complex_members(first, last, step, reader.middle)
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

    # --- niche trackers ---------------------------------------------------------------

    def _tracker_results(self, analysis_id: uuid.UUID) -> ZigzagResultReader:
        reader = self.zigzag_results(analysis_id)
        if not reader.has_trackers:
            raise NotFoundError(TRACKERS_MISSING)
        return reader

    @staticmethod
    def _compare(
        reader: ZigzagResultReader, epsilon_index: int, long_lifetime: int
    ) -> list[MethodSummary]:
        try:
            zigzag = reader.bar_array(epsilon_index, 0)
            trackers = {m.value: reader.tracker_bars(epsilon_index, m) for m in TrackerMethod}
        except KeyError as exc:
            raise NotFoundError(str(exc.args[0])) from None
        return compare_with_zigzag(zigzag, trackers, reader.n_steps, long_lifetime)

    def tracker_bars(
        self, analysis_id: uuid.UUID, epsilon_index: int, method: TrackerMethod, min_lifetime: int
    ) -> TrackerBarsView:
        reader = self._tracker_results(analysis_id)
        try:
            bars = reader.tracker_bars(epsilon_index, method)
            zigzag = reader.bar_array(epsilon_index, 0)
        except KeyError as exc:
            raise NotFoundError(str(exc.args[0])) from None
        # matched against every zigzag bar, then filtered for display
        by_step = matched(bars, zigzag, Resolution.STEP)
        by_generation = matched(bars, zigzag, Resolution.GENERATION)
        keep = (bars[:, 1] - bars[:, 0]) >= min_lifetime
        return TrackerBarsView(
            epsilon=reader.epsilons[epsilon_index],
            method=method,
            n_generations=reader.n_generations,
            n_steps=reader.n_steps,
            bars=bars[keep],
            matched_step=by_step[keep],
            matched_generation=by_generation[keep],
        )

    def tracker_comparison(
        self, analysis_id: uuid.UUID, epsilon_index: int, long_lifetime: int
    ) -> TrackerComparison:
        reader = self._tracker_results(analysis_id)
        methods = self._compare(reader, epsilon_index, long_lifetime)
        return TrackerComparison(
            epsilon=reader.epsilons[epsilon_index],
            n_generations=reader.n_generations,
            n_steps=reader.n_steps,
            long_lifetime=long_lifetime,
            methods=methods,
        )

    def _tracker_runs(
        self, analyses: Sequence[AnalysisRow], epsilon_index: int, long_lifetime: int
    ) -> TrackerRuns:
        values: dict[str, dict[str, list[float | None]]] = {}
        epsilon: float | None = None
        skipped = 0
        for analysis in analyses:
            reader = self.zigzag_results(analysis.id)
            if not reader.has_trackers:
                skipped += 1
                continue
            for summary in self._compare(reader, epsilon_index, long_lifetime):
                fields = values.setdefault(summary.method, {f: [] for f in TRACKER_RUN_FIELDS})
                for name in TRACKER_RUN_FIELDS:
                    value = getattr(summary, name)
                    fields[name].append(None if value is None else float(value))
            epsilon = reader.epsilons[epsilon_index]
        if epsilon is None:
            raise NotFoundError(TRACKERS_MISSING)
        n_runs = len(analyses) - skipped
        return TrackerRuns(epsilon, long_lifetime, n_runs, skipped, values)

    def tracker_batch_runs(
        self, batch_id: uuid.UUID, epsilon_index: int, long_lifetime: int
    ) -> TrackerRuns:
        analyses = [
            a
            for a in self._analyses.list_batch(batch_id)
            if a.kind == ZIGZAG_ANALYSIS and a.status == RunStatus.COMPLETED
        ]
        if not analyses:
            raise NotFoundError(f"no completed zigzag analysis in batch {batch_id}")
        return self._tracker_runs(analyses, epsilon_index, long_lifetime)

    def tracker_group_runs(
        self, experiment_id: uuid.UUID, key: str, epsilon_index: int, long_lifetime: int
    ) -> TrackerRuns:
        group = next((g for g in self.analysis_groups(experiment_id) if g.key == key), None)
        if group is None:
            raise NotFoundError(f"no analysis group {key} in experiment {experiment_id}")
        if group.kind != ZIGZAG_ANALYSIS:
            raise ConflictError("niche trackers are computed by zigzag analyses only")
        if not group.completed:
            raise ConflictError("no analysis of this group has completed yet")
        return self._tracker_runs(group.completed, epsilon_index, long_lifetime)

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
            generations, series = self._zigzag_series(analysis, epsilon_index, dimension)
            length = min(length or len(generations), len(generations))
            for name in BATCH_SERIES:
                samples.setdefault(name, []).append(series[name])
        assert length is not None
        quartiles = {}
        for name, runs in samples.items():
            stacked = np.vstack([values[:length] for values in runs])
            q1, median, q3 = np.percentile(stacked, [25, 50, 75], axis=0)
            quartiles[name] = Quartiles(q1=q1, median=median, q3=q3)
        return ZigzagBatchSummary(
            generations=list(range(length)), n_runs=len(analyses), series=quartiles
        )

    def _zigzag_series(
        self, analysis: AnalysisRow, epsilon_index: int, dimension: int
    ) -> RunSeries:
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
        series["births"] = series["births_variation"] + series["births_selection"]
        series["deaths"] = series["deaths_variation"] + series["deaths_selection"]
        return list(range(reader.n_generations + 1)), series

    def _topology_series(self, analysis: AnalysisRow, dimension: int) -> RunSeries:
        reader = self.results(analysis.id)
        if dimension > reader.max_dimension:
            raise NotFoundError(f"H{dimension} was not computed")
        table = reader.series().to_pydict()
        rows = [i for i, d in enumerate(table["dimension"]) if d == dimension]
        names = ["n_bars", "total_persistence", "persistent_entropy"]
        names += [f"{m}_{ref}" for m in reader.metrics for ref in ("previous", "final")]
        series = {
            name: np.array([table[name][i] for i in rows], dtype=np.float64) for name in names
        }
        return [table["generation"][i] for i in rows], series

    def analysis_groups(self, experiment_id: uuid.UUID) -> list[AnalysisGroup]:
        """Analyses of an experiment grouped by configuration, newest group first."""
        members: dict[str, list[AnalysisRow]] = {}
        for analysis in self.list_for_experiment(experiment_id):  # newest first
            members.setdefault(group_key(analysis.kind, analysis.config), []).append(analysis)
        groups = []
        for key, analyses in members.items():
            completed: dict[uuid.UUID, AnalysisRow] = {}
            active: set[uuid.UUID] = set()
            for analysis in analyses:
                if analysis.status == RunStatus.COMPLETED:
                    completed.setdefault(analysis.run_id, analysis)
                elif analysis.status.is_active:
                    active.add(analysis.run_id)
            if not completed and not active:
                continue  # only failed analyses
            groups.append(
                AnalysisGroup(
                    key=key,
                    kind=analyses[0].kind,
                    config=analyses[0].config,
                    completed=sorted(completed.values(), key=lambda a: a.run.index),
                    pending=len(active - completed.keys()),
                    created_at=analyses[0].created_at,
                )
            )
        return groups

    def analysis_group_summary(
        self, experiment_id: uuid.UUID, key: str, dimension: int, epsilon_index: int
    ) -> GroupSummary:
        """Median and quartiles across the runs of a group, per generation."""
        group = next((g for g in self.analysis_groups(experiment_id) if g.key == key), None)
        if group is None:
            raise NotFoundError(f"no analysis group {key} in experiment {experiment_id}")
        if not group.completed:
            raise ConflictError("no analysis of this group has completed yet")
        if group.kind == ZIGZAG_ANALYSIS:
            runs = [self._zigzag_series(a, epsilon_index, dimension) for a in group.completed]
        else:
            runs = [self._topology_series(a, dimension) for a in group.completed]
        generations, n_runs, series = summarize_runs(runs)
        totals = {}
        for name in ZIGZAG_EVENT_SERIES if group.kind == ZIGZAG_ANALYSIS else ():
            sums = [float(values[name].sum()) for _, values in runs]
            q1, median, q3 = np.percentile(sums, [25, 50, 75])
            totals[name] = Spread(q1=float(q1), median=float(median), q3=float(q3))
        return GroupSummary(
            kind=group.kind,
            generations=generations,
            n_runs=n_runs,
            series=series,
            totals=totals,
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
        survivors = SELECTORS[PointCloudKind.SURVIVORS]
        diameters: list[float] = []
        spacings: list[float] = []
        population_spacings: list[float] = []
        for snapshot in reader.iter_generations():
            if snapshot.generation not in sampled:
                continue
            points = normalizer.transform(selector.select(snapshot))
            diameters.append(diameter(points))
            spacings.append(float(np.median(nearest_neighbour_distances(points))))
            population = normalizer.transform(survivors.select(snapshot))
            population_spacings.append(float(np.median(nearest_neighbour_distances(population))))
        largest = max(diameters)
        spacing = float(np.median(spacings))
        population_spacing = float(np.median(population_spacings))
        return EpsilonSuggestion(
            max_diameter=largest,
            median_diameter=float(np.median(diameters)),
            median_nearest_neighbour=spacing,
            suggested_max_epsilon=round_up(largest),
            suggested_scales=sorted(
                {round_up(population_spacing * f) for f in ZIGZAG_SCALE_FACTORS}
            ),
        )
