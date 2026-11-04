"""Executes one run of an experiment, independently of any infrastructure."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from esphea.core.observer import AlgorithmObserver
from esphea.core.problem import KnownParetoFront, Problem
from esphea.core.termination import AnyOf, MaxGenerations, Termination
from esphea.experiments.config import ExperimentConfig
from esphea.experiments.observers import (
    IndicatorObserver,
    MetricsSink,
    ProgressObserver,
    ProgressReporter,
    SnapshotObserver,
)
from esphea.experiments.registry import AlgorithmRegistry, ProblemRegistry
from esphea.experiments.storage import SnapshotWriter
from esphea.metrics import GD, IGD, Hypervolume, IGDPlus, QualityIndicator

HV_REFERENCE_MARGIN = 1.1
"""Hypervolume reference point = nadir point scaled by this factor."""


class CallbackTermination(Termination):
    """Stops when ``should_cancel`` returns true (checked at most every ``every`` generations)."""

    def __init__(self, should_cancel: Callable[[], bool], *, every: int = 1) -> None:
        self._should_cancel = should_cancel
        self._every = every
        self.triggered = False

    def should_stop(self, generation: int) -> bool:
        if generation % self._every == 0 and self._should_cancel():
            self.triggered = True
        return self.triggered


@dataclass(frozen=True, slots=True)
class RunOutcome:
    generations: int
    cancelled: bool


def build_indicators(config: ExperimentConfig, problem: Problem) -> list[QualityIndicator]:
    """Indicators enabled in ``config`` that ``problem`` can support."""
    if not isinstance(problem, KnownParetoFront):
        return []
    indicators: list[QualityIndicator] = []
    metrics = config.metrics
    if metrics.gd or metrics.igd or metrics.igd_plus:
        front = problem.pareto_front(metrics.reference_front_size)
        if metrics.gd:
            indicators.append(GD(front))
        if metrics.igd:
            indicators.append(IGD(front))
        if metrics.igd_plus:
            indicators.append(IGDPlus(front))
    if metrics.hv:
        indicators.append(Hypervolume(problem.nadir_point * HV_REFERENCE_MARGIN))
    return indicators


class RunExecutor:
    """Builds the algorithm described by a configuration and runs it with observers."""

    def __init__(self, problems: ProblemRegistry, algorithms: AlgorithmRegistry) -> None:
        self._problems = problems
        self._algorithms = algorithms

    def execute(
        self,
        config: ExperimentConfig,
        seed: int,
        *,
        metrics_sink: MetricsSink,
        progress: ProgressReporter,
        snapshot_dir: Path | None,
        should_cancel: Callable[[], bool] = lambda: False,
    ) -> RunOutcome:
        problem = self._problems.build(config.problem)
        algorithm = self._algorithms.build(config.algorithm, problem)

        indicator_observer = IndicatorObserver(
            build_indicators(config, problem), metrics_sink, every=config.metrics.every
        )
        observers: list[AlgorithmObserver] = [indicator_observer]
        if config.snapshots.enabled and snapshot_dir is not None:
            writer = SnapshotWriter(
                snapshot_dir,
                n_var=problem.n_var,
                n_obj=problem.n_obj,
                precision=config.snapshots.precision,
                decision_variables=config.snapshots.decision_variables,
            )
            observers.append(SnapshotObserver(writer, every=config.snapshots.every))
        observers.append(ProgressObserver(progress, n_gen=config.n_gen, metrics=indicator_observer))

        cancellation = CallbackTermination(should_cancel)
        result = algorithm.run(
            AnyOf([MaxGenerations(config.n_gen), cancellation]),
            np.random.default_rng(seed),
            observers,
        )
        return RunOutcome(generations=result.generations, cancelled=cancellation.triggered)
