"""Persistent-homology analysis of every stored generation of a run."""

from collections.abc import Callable, Sequence

import numpy as np

from esphea.core.types import FloatArray
from esphea.experiments.storage import GenerationSnapshot, SnapshotReader
from esphea.topology.clouds import SELECTORS, Normalizer
from esphea.topology.config import TopologyAnalysisConfig
from esphea.topology.diagram import PersistenceDiagram
from esphea.topology.distances import DiagramDistance, diameter, hausdorff_distance
from esphea.topology.persistence import PersistenceComputer
from esphea.topology.storage import GenerationTopology, TopologyResultWriter

MATRIX_MAX_GENERATIONS = 100


class AnalysisInterruptedError(RuntimeError):
    """Raised when ``should_stop`` asks the analysis to stop."""


def evenly_spaced(values: Sequence[int], count: int) -> list[int]:
    """At most ``count`` values of ``values``, evenly spaced and including both ends."""
    if len(values) <= count:
        return list(values)
    positions = np.unique(np.linspace(0, len(values) - 1, count).round().astype(int))
    return [values[i] for i in positions]


class TopologyAnalyzer:
    """Computes, for each stored generation ``g``:

    * the Vietoris-Rips persistence diagram of the selected point cloud,
      truncated at ``max_epsilon``;
    * distances between the diagrams of ``g`` and of the previous stored
      generation, and of ``g`` and of the final generation, per homology
      dimension and metric;
    * the Hausdorff distance between the same point clouds, the baseline given
      by the stability theorem (``bottleneck <= 2 * hausdorff``);
    * optionally, distances between all pairs of (up to 100) generations.
    """

    def __init__(
        self,
        config: TopologyAnalysisConfig,
        *,
        computer: PersistenceComputer,
        distances: Sequence[DiagramDistance],
        normalizer: Normalizer,
    ) -> None:
        self._config = config
        self._computer = computer
        self._distances = tuple(distances)
        self._normalizer = normalizer
        self._selector = SELECTORS[config.point_cloud]

    @property
    def metric_names(self) -> list[str]:
        return [distance.name for distance in self._distances]

    def analyze(
        self,
        reader: SnapshotReader,
        writer: TopologyResultWriter,
        *,
        progress: Callable[[int, int], None] = lambda done, total: None,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        generations = reader.generations()
        if not generations:
            raise ValueError("the run has no stored generations")
        matrix_generations = (
            evenly_spaced(generations, MATRIX_MAX_GENERATIONS)
            if self._config.distance_matrix
            else []
        )
        total = len(generations) + len(matrix_generations)

        final_points, final_diagram = self._analyse_cloud(reader.read(generations[-1]))
        previous: tuple[FloatArray, PersistenceDiagram] | None = None
        kept: dict[int, PersistenceDiagram] = {}
        for done, snapshot in enumerate(reader.iter_generations(), start=1):
            if should_stop():
                raise AnalysisInterruptedError
            points, diagram = self._analyse_cloud(snapshot)
            writer.add_generation(
                GenerationTopology(
                    generation=snapshot.generation,
                    n_points=int(points.shape[0]),
                    diameter=diameter(points),
                    diagram=diagram,
                    hausdorff_previous=None
                    if previous is None
                    else hausdorff_distance(points, previous[0]),
                    hausdorff_final=hausdorff_distance(points, final_points),
                    distances_previous=None
                    if previous is None
                    else self._compare(diagram, previous[1]),
                    distances_final=self._compare(diagram, final_diagram),
                )
            )
            if snapshot.generation in matrix_generations:
                kept[snapshot.generation] = diagram
            previous = (points, diagram)
            progress(done, total)

        if matrix_generations:
            self._pairwise(
                diagrams=kept,
                generations=matrix_generations,
                writer=writer,
                done=len(generations),
                total=total,
                progress=progress,
                should_stop=should_stop,
            )
        writer.close()

    def _analyse_cloud(self, snapshot: GenerationSnapshot) -> tuple[FloatArray, PersistenceDiagram]:
        points = self._normalizer.transform(self._selector.select(snapshot))
        diagram = self._computer.compute(
            points,
            max_dimension=self._config.max_dimension,
            max_epsilon=self._config.max_epsilon,
        )
        return points, diagram

    def _compare(
        self, first: PersistenceDiagram, second: PersistenceDiagram
    ) -> dict[str, list[float]]:
        return {
            distance.name: [
                distance(first.bars[k], second.bars[k]) for k in range(first.max_dimension + 1)
            ]
            for distance in self._distances
        }

    def _pairwise(
        self,
        *,
        diagrams: dict[int, PersistenceDiagram],
        generations: list[int],
        writer: TopologyResultWriter,
        done: int,
        total: int,
        progress: Callable[[int, int], None],
        should_stop: Callable[[], bool],
    ) -> None:
        n = len(generations)
        matrices = {
            (k, d.name): np.zeros((n, n))
            for k in range(self._config.max_dimension + 1)
            for d in self._distances
        }
        for i, gi in enumerate(generations):
            if should_stop():
                raise AnalysisInterruptedError
            for j in range(i + 1, n):
                distances = self._compare(diagrams[gi], diagrams[generations[j]])
                for (k, name), matrix in matrices.items():
                    matrix[i, j] = matrix[j, i] = distances[name][k]
            progress(done + i + 1, total)
        for (k, name), matrix in matrices.items():
            writer.add_matrix(k, name, generations, matrix)
