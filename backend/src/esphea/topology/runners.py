"""One runner per kind of analysis: validation and execution against a run's snapshots."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from esphea.core.problem import Problem
from esphea.experiments.storage import SnapshotReader
from esphea.topology.analysis import TopologyAnalyzer
from esphea.topology.clouds import PointCloudKind, build_normalizer
from esphea.topology.config import (
    MAX_POINTS,
    TOPOLOGY_ANALYSIS,
    ZIGZAG_ANALYSIS,
    TopologyAnalysisConfig,
    ZigzagAnalysisConfig,
)
from esphea.topology.distances import BottleneckDistance, WassersteinDistance
from esphea.topology.persistence import VietorisRips
from esphea.topology.storage import TopologyResultWriter
from esphea.topology.zigzag_analysis import ZigzagAnalyzer
from esphea.topology.zigzag_storage import ZigzagResultWriter

type AnalysisConfigModel = TopologyAnalysisConfig | ZigzagAnalysisConfig
type Progress = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    """What a runner needs to know about the analysed run."""

    snapshots: SnapshotReader
    problem: Problem
    population_size: int


class AnalysisRunner(ABC):
    kind: str

    @abstractmethod
    def validate(self, config: AnalysisConfigModel, context: AnalysisContext) -> None:
        """Raise ``ValueError`` when ``config`` cannot be computed on this run."""

    @abstractmethod
    def run(
        self,
        config: AnalysisConfigModel,
        context: AnalysisContext,
        output: Path,
        *,
        progress: Progress,
        should_stop: Callable[[], bool],
    ) -> None:
        """Compute the analysis into ``output`` (written atomically)."""


def _check_points(points: int) -> None:
    if points > MAX_POINTS:
        raise ValueError(
            f"point clouds of {points} points exceed the limit of {MAX_POINTS} for Vietoris-Rips"
        )


class TopologyRunner(AnalysisRunner):
    kind = TOPOLOGY_ANALYSIS

    def validate(self, config: AnalysisConfigModel, context: AnalysisContext) -> None:
        assert isinstance(config, TopologyAnalysisConfig)
        factor = 2 if config.point_cloud == PointCloudKind.MERGED else 1
        _check_points(context.population_size * factor)
        build_normalizer(config.normalization, context.problem)

    def run(
        self,
        config: AnalysisConfigModel,
        context: AnalysisContext,
        output: Path,
        *,
        progress: Progress,
        should_stop: Callable[[], bool],
    ) -> None:
        assert isinstance(config, TopologyAnalysisConfig)
        analyzer = TopologyAnalyzer(
            config,
            computer=VietorisRips(),
            distances=[BottleneckDistance(), WassersteinDistance(1)],
            normalizer=build_normalizer(config.normalization, context.problem),
        )
        writer = TopologyResultWriter(
            output,
            max_dimension=config.max_dimension,
            max_epsilon=config.max_epsilon,
            metrics=analyzer.metric_names,
        )
        analyzer.analyze(context.snapshots, writer, progress=progress, should_stop=should_stop)


class ZigzagRunner(AnalysisRunner):
    kind = ZIGZAG_ANALYSIS

    def validate(self, config: AnalysisConfigModel, context: AnalysisContext) -> None:
        assert isinstance(config, ZigzagAnalysisConfig)
        snapshots = context.snapshots
        if not snapshots.has_individual_ids:
            raise ValueError(
                "this run was stored without individual identities; run it again to analyse it"
            )
        generations = snapshots.generations()
        if generations != list(range(len(generations))):
            raise ValueError("the zigzag needs every generation stored (snapshot every 1)")
        _check_points(2 * context.population_size)
        build_normalizer(config.normalization, context.problem)

    def run(
        self,
        config: AnalysisConfigModel,
        context: AnalysisContext,
        output: Path,
        *,
        progress: Progress,
        should_stop: Callable[[], bool],
    ) -> None:
        assert isinstance(config, ZigzagAnalysisConfig)
        analyzer = ZigzagAnalyzer(
            config, normalizer=build_normalizer(config.normalization, context.problem)
        )
        writer = ZigzagResultWriter(
            output, epsilons=config.epsilons, max_dimension=config.max_dimension
        )
        analyzer.analyze(context.snapshots, writer, progress=progress, should_stop=should_stop)


def default_runners() -> dict[str, AnalysisRunner]:
    runners: list[AnalysisRunner] = [TopologyRunner(), ZigzagRunner()]
    return {runner.kind: runner for runner in runners}
