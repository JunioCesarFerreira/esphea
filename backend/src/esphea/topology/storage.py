"""Columnar storage of topology analysis results (Apache Parquet).

An analysis directory holds:

* ``meta.json`` - configuration echo, stored generations and metric names;
* ``diagrams.parquet`` - ``generation, dimension, birth, death, truncated``;
* ``series.parquet`` - per generation and dimension: ``n_bars``,
  ``total_persistence``, ``persistent_entropy`` and, for every metric,
  ``<metric>_previous`` (to the previous stored generation) and ``<metric>_final``;
* ``clouds.parquet`` - per generation: ``n_points``, ``diameter``,
  ``hausdorff_previous``, ``hausdorff_final``;
* ``matrix.parquet`` (optional) - ``dimension, metric, row, column, value``
  for the upper triangle of the pairwise distance matrix.

Results are written to a temporary directory and renamed atomically, so a
directory either holds a complete analysis or does not exist.
"""

import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from esphea.core.types import AnyArray, FloatArray, IntArray
from esphea.topology.diagram import PersistenceDiagram
from esphea.topology.summaries import betti_curve, persistent_entropy, total_persistence

SCHEMA_VERSION = 1
_META = "meta.json"


def analysis_directory(
    runs_dir: Path, run_id: uuid.UUID, analysis_id: uuid.UUID, attempt: int
) -> Path:
    """``<runs_dir>/<run-id>/analyses/<analysis-id>/attempt-<n>``."""
    return runs_dir / str(run_id) / "analyses" / str(analysis_id) / f"attempt-{attempt}"


@dataclass(frozen=True, slots=True)
class GenerationTopology:
    """Everything computed for one stored generation."""

    generation: int
    n_points: int
    diameter: float
    diagram: PersistenceDiagram
    hausdorff_previous: float | None
    hausdorff_final: float
    # metric name -> per-dimension distances (None for the first generation)
    distances_previous: dict[str, list[float]] | None
    distances_final: dict[str, list[float]]


@dataclass(slots=True)
class _Columns:
    data: dict[str, list[Any]] = field(default_factory=dict)

    def append(self, **values: Any) -> None:
        for name, value in values.items():
            self.data.setdefault(name, []).append(value)

    def table(self) -> pa.Table:
        return pa.table(self.data)


class TopologyResultWriter:
    def __init__(
        self, directory: Path, *, max_dimension: int, max_epsilon: float, metrics: list[str]
    ) -> None:
        self._directory = directory
        self._max_dimension = max_dimension
        self._max_epsilon = max_epsilon
        self._metrics = metrics
        self._generations: list[int] = []
        self._diagram_rows: list[tuple[AnyArray, AnyArray, FloatArray, AnyArray]] = []
        self._series = _Columns()
        self._clouds = _Columns()
        self._matrix = _Columns()
        self._matrix_generations: list[int] = []

    def add_generation(self, result: GenerationTopology) -> None:
        generation = result.generation
        self._generations.append(generation)
        nan = float("nan")
        self._clouds.append(
            generation=generation,
            n_points=result.n_points,
            diameter=result.diameter,
            hausdorff_previous=nan
            if result.hausdorff_previous is None
            else result.hausdorff_previous,
            hausdorff_final=result.hausdorff_final,
        )
        diagram = result.diagram
        for k in range(diagram.max_dimension + 1):
            bars = diagram.bars[k]
            n = bars.shape[0]
            self._diagram_rows.append(
                (
                    np.full(n, generation, dtype=np.int32),
                    np.full(n, k, dtype=np.int8),
                    bars,
                    diagram.truncated[k],
                )
            )
            row: dict[str, Any] = {
                "generation": generation,
                "dimension": k,
                "n_bars": int(n),
                "total_persistence": total_persistence(bars),
                "persistent_entropy": persistent_entropy(bars),
            }
            for metric in self._metrics:
                previous = result.distances_previous
                row[f"{metric}_previous"] = nan if previous is None else previous[metric][k]
                row[f"{metric}_final"] = result.distances_final[metric][k]
            self._series.append(**row)

    def add_matrix(
        self, dimension: int, metric: str, generations: list[int], values: FloatArray
    ) -> None:
        self._matrix_generations = generations
        rows, columns = np.triu_indices(len(generations))
        for i, j in zip(rows, columns, strict=True):
            self._matrix.append(
                dimension=dimension,
                metric=metric,
                row=generations[i],
                column=generations[j],
                value=float(values[i, j]),
            )

    def close(self) -> None:
        temporary = self._directory.with_name(self._directory.name + ".tmp")
        shutil.rmtree(temporary, ignore_errors=True)
        temporary.mkdir(parents=True)
        generations, dimensions, bars, truncated = (
            zip(*self._diagram_rows, strict=True) if self._diagram_rows else ((), (), (), ())
        )
        all_bars = np.vstack(bars) if bars else np.empty((0, 2))
        diagrams = pa.table(
            {
                "generation": np.concatenate(generations or (np.empty(0, np.int32),)),
                "dimension": np.concatenate(dimensions or (np.empty(0, np.int8),)),
                "birth": all_bars[:, 0],
                "death": all_bars[:, 1],
                "truncated": np.concatenate(truncated or (np.empty(0, np.bool_),)),
            }
        )
        pq.write_table(diagrams, temporary / "diagrams.parquet", compression="zstd")
        pq.write_table(self._series.table(), temporary / "series.parquet", compression="zstd")
        pq.write_table(self._clouds.table(), temporary / "clouds.parquet", compression="zstd")
        if self._matrix.data:
            pq.write_table(self._matrix.table(), temporary / "matrix.parquet", compression="zstd")
        meta = {
            "schema_version": SCHEMA_VERSION,
            "max_dimension": self._max_dimension,
            "max_epsilon": self._max_epsilon,
            "metrics": self._metrics,
            "generations": self._generations,
            "matrix_generations": self._matrix_generations,
        }
        (temporary / _META).write_text(json.dumps(meta))
        shutil.rmtree(self._directory, ignore_errors=True)
        temporary.rename(self._directory)


class TopologyResultReader:
    def __init__(self, directory: Path) -> None:
        meta_path = directory / _META
        if not meta_path.exists():
            raise FileNotFoundError(f"no analysis results in {directory}")
        meta = json.loads(meta_path.read_text())
        self._directory = directory
        self.max_dimension: int = meta["max_dimension"]
        self.max_epsilon: float = meta["max_epsilon"]
        self.metrics: list[str] = meta["metrics"]
        self.generations: list[int] = meta["generations"]
        self.matrix_generations: list[int] = meta["matrix_generations"]

    def diagram(self, generation: int) -> PersistenceDiagram:
        if generation not in self.generations:
            raise KeyError(f"generation {generation} was not analysed")
        table = pq.read_table(
            self._directory / "diagrams.parquet", filters=[("generation", "=", generation)]
        )
        dimension = table.column("dimension").to_numpy()
        births = table.column("birth").to_numpy()
        deaths = table.column("death").to_numpy()
        truncated = table.column("truncated").to_numpy(zero_copy_only=False)
        bars, flags = [], []
        for k in range(self.max_dimension + 1):
            mask = dimension == k
            bars.append(np.column_stack((births[mask], deaths[mask])))
            flags.append(truncated[mask].astype(bool))
        return PersistenceDiagram(self.max_epsilon, tuple(bars), tuple(flags))

    def series(self) -> pa.Table:
        return pq.read_table(self._directory / "series.parquet")

    def clouds(self) -> pa.Table:
        return pq.read_table(self._directory / "clouds.parquet")

    def betti_curves(self, dimension: int, resolution: int) -> tuple[FloatArray, IntArray]:
        """Scale grid and the ``(n_generations, resolution)`` Betti numbers of ``H_dimension``."""
        grid = np.linspace(0.0, self.max_epsilon, resolution)
        table = pq.read_table(
            self._directory / "diagrams.parquet", filters=[("dimension", "=", dimension)]
        )
        generation = table.column("generation").to_numpy()
        bars = np.column_stack((table.column("birth").to_numpy(), table.column("death").to_numpy()))
        truncated = table.column("truncated").to_numpy(zero_copy_only=False).astype(bool)
        curves = np.zeros((len(self.generations), resolution), dtype=np.intp)
        for row, g in enumerate(self.generations):
            mask = generation == g
            curves[row] = betti_curve(bars[mask], truncated[mask], grid)
        return grid, curves

    def matrix(self, dimension: int, metric: str) -> tuple[list[int], FloatArray]:
        path = self._directory / "matrix.parquet"
        if not path.exists():
            raise KeyError("the distance matrix was not computed for this analysis")
        table = pq.read_table(path).filter(
            (pc.field("dimension") == dimension) & (pc.field("metric") == metric)
        )
        generations = self.matrix_generations
        index = {g: i for i, g in enumerate(generations)}
        values = np.zeros((len(generations), len(generations)))
        rows = [index[g] for g in table.column("row").to_pylist()]
        columns = [index[g] for g in table.column("column").to_pylist()]
        values[rows, columns] = table.column("value").to_numpy()
        values[columns, rows] = table.column("value").to_numpy()
        return generations, values
