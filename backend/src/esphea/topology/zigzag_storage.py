"""Columnar storage of zigzag analysis results (Apache Parquet).

An analysis directory holds ``meta.json`` and:

* ``individuals.parquet`` - ``individual_id, first_step, last_step, f_*``
  (points as analysed, i.e. after normalisation);
* ``bars.parquet`` - ``epsilon_index, bar, dimension, birth, death, kind,
  birth_cause, death_cause`` (alive on steps ``[birth, death - 1]``);
* ``representatives.parquet`` - ``epsilon_index, bar, start, end, simplex``
  (one row per simplex of the representative cycle on steps ``[start, end]``).

Written to a temporary directory and renamed atomically.
"""

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from esphea.core.types import FloatArray, IntArray
from esphea.topology.zigzag import (
    Cause,
    ZigzagResult,
    ZigzagSequence,
    step_generation,
)

SCHEMA_VERSION = 1
_META = "meta.json"


class ZigzagResultWriter:
    def __init__(self, directory: Path, *, epsilons: tuple[float, ...], max_dimension: int) -> None:
        self._directory = directory
        self._epsilons = epsilons
        self._max_dimension = max_dimension
        self._n_generations = 0
        self._individuals: pa.Table | None = None
        self._bars: dict[str, list[Any]] = {}
        self._representatives: dict[str, list[Any]] = {}
        self._scales: list[dict[str, Any]] = []

    def write_sequence(self, sequence: ZigzagSequence) -> None:
        self._n_generations = sequence.n_generations
        columns: dict[str, Any] = {
            "individual_id": np.arange(sequence.points.shape[0], dtype=np.int64),
            "first_step": sequence.first.astype(np.int32),
            "last_step": sequence.last.astype(np.int32),
        }
        for j in range(sequence.points.shape[1]):
            columns[f"f_{j}"] = sequence.points[:, j]
        self._individuals = pa.table(columns)

    @staticmethod
    def _append(columns: dict[str, list[Any]], row: dict[str, Any]) -> None:
        for name, value in row.items():
            columns.setdefault(name, []).append(value)

    def add_result(self, epsilon_index: int, result: ZigzagResult) -> None:
        self._scales.append(
            {
                "epsilon": result.epsilon,
                "n_simplices": result.n_simplices,
                "representatives_skipped": result.representatives_skipped,
            }
        )
        for index, bar in enumerate(result.bars):
            self._append(
                self._bars,
                {
                    "epsilon_index": epsilon_index,
                    "bar": index,
                    "dimension": bar.dimension,
                    "birth": bar.birth,
                    "death": bar.death,
                    "kind": bar.kind,
                    "birth_cause": bar.birth_cause.value,
                    "death_cause": bar.death_cause.value,
                },
            )
        for index, segments in result.representatives.items():
            rows = [
                {"start": segment.start, "end": segment.end, "simplex": list(simplex)}
                for segment in segments
                for simplex in segment.simplices
            ]
            # An unavailable representative is recorded too, so it is not mistaken for "not kept".
            for row in rows or [{"start": -1, "end": -1, "simplex": []}]:
                self._append(
                    self._representatives, {"epsilon_index": epsilon_index, "bar": index, **row}
                )

    def close(self) -> None:
        if self._individuals is None:
            raise RuntimeError("write_sequence must be called before close")
        temporary = self._directory.with_name(self._directory.name + ".tmp")
        shutil.rmtree(temporary, ignore_errors=True)
        temporary.mkdir(parents=True)
        pq.write_table(self._individuals, temporary / "individuals.parquet", compression="zstd")
        bars_schema = pa.schema(
            [
                ("epsilon_index", pa.int8()),
                ("bar", pa.int32()),
                ("dimension", pa.int8()),
                ("birth", pa.int32()),
                ("death", pa.int32()),
                ("kind", pa.string()),
                ("birth_cause", pa.string()),
                ("death_cause", pa.string()),
            ]
        )
        pq.write_table(
            pa.table(self._bars or {n: [] for n in bars_schema.names}, schema=bars_schema),
            temporary / "bars.parquet",
            compression="zstd",
        )
        representatives_schema = pa.schema(
            [
                ("epsilon_index", pa.int8()),
                ("bar", pa.int32()),
                ("start", pa.int32()),
                ("end", pa.int32()),
                ("simplex", pa.list_(pa.int64())),
            ]
        )
        pq.write_table(
            pa.table(
                self._representatives or {n: [] for n in representatives_schema.names},
                schema=representatives_schema,
            ),
            temporary / "representatives.parquet",
            compression="zstd",
        )
        meta = {
            "schema_version": SCHEMA_VERSION,
            "epsilons": list(self._epsilons),
            "max_dimension": self._max_dimension,
            "n_generations": self._n_generations,
            "scales": self._scales,
        }
        (temporary / _META).write_text(json.dumps(meta))
        shutil.rmtree(self._directory, ignore_errors=True)
        temporary.rename(self._directory)


@dataclass(frozen=True, slots=True)
class ZigzagEvents:
    """Births and deaths per generation, by cause (index = generation)."""

    births_variation: IntArray
    births_selection: IntArray
    deaths_variation: IntArray
    deaths_selection: IntArray


class ZigzagResultReader:
    def __init__(self, directory: Path) -> None:
        meta_path = directory / _META
        if not meta_path.exists():
            raise FileNotFoundError(f"no zigzag results in {directory}")
        meta = json.loads(meta_path.read_text())
        self._directory = directory
        self.epsilons: list[float] = meta["epsilons"]
        self.max_dimension: int = meta["max_dimension"]
        self.n_generations: int = meta["n_generations"]
        self.n_steps = 2 * self.n_generations + 1
        self.scales: list[dict[str, Any]] = meta.get("scales", [])

    def _check(self, epsilon_index: int, dimension: int) -> None:
        if not 0 <= epsilon_index < len(self.epsilons):
            raise KeyError(f"epsilon index {epsilon_index} does not exist")
        if not 0 <= dimension <= self.max_dimension:
            raise KeyError(f"H{dimension} was not computed")

    def bars(self, epsilon_index: int, dimension: int) -> pa.Table:
        self._check(epsilon_index, dimension)
        return pq.read_table(
            self._directory / "bars.parquet",
            filters=[("epsilon_index", "=", epsilon_index), ("dimension", "=", dimension)],
        )

    def bar(self, epsilon_index: int, bar: int) -> dict[str, Any]:
        table = pq.read_table(
            self._directory / "bars.parquet",
            filters=[("epsilon_index", "=", epsilon_index), ("bar", "=", bar)],
        ).to_pylist()
        if not table:
            raise KeyError(f"bar {bar} does not exist")
        return dict(table[0])

    def betti(self, epsilon_index: int, dimension: int) -> IntArray:
        """Number of features alive at every step."""
        table = self.bars(epsilon_index, dimension)
        alive = np.zeros(self.n_steps + 1, dtype=np.intp)
        np.add.at(alive, table.column("birth").to_numpy(), 1)
        np.add.at(alive, table.column("death").to_numpy(), -1)
        return np.cumsum(alive)[: self.n_steps]

    def events(self, epsilon_index: int, dimension: int) -> ZigzagEvents:
        table = self.bars(epsilon_index, dimension).to_pydict()
        counts = {
            key: np.zeros(self.n_generations + 1, dtype=np.intp) for key in ("bv", "bs", "dv", "ds")
        }
        for birth, cause in zip(table["birth"], table["birth_cause"], strict=True):
            if cause == Cause.VARIATION:
                counts["bv"][step_generation(birth)] += 1
            elif cause == Cause.SELECTION:
                counts["bs"][step_generation(birth)] += 1
        for death, cause in zip(table["death"], table["death_cause"], strict=True):
            if cause == Cause.VARIATION:
                counts["dv"][step_generation(death)] += 1
            elif cause == Cause.SELECTION:
                counts["ds"][step_generation(death)] += 1
        return ZigzagEvents(counts["bv"], counts["bs"], counts["dv"], counts["ds"])

    def representative_bars(self, epsilon_index: int) -> dict[int, bool]:
        """Bars whose representative was attempted -> whether it is available."""
        table = pq.read_table(
            self._directory / "representatives.parquet",
            columns=["bar", "start"],
            filters=[("epsilon_index", "=", epsilon_index)],
        ).to_pydict()
        available: dict[int, bool] = {}
        for bar, start in zip(table["bar"], table["start"], strict=True):
            available[bar] = available.get(bar, False) or start >= 0
        return available

    def representative(self, epsilon_index: int, bar: int, step: int) -> list[list[int]] | None:
        """Simplices (as individual ids) representing ``bar`` at ``step``; None if unknown."""
        table = pq.read_table(
            self._directory / "representatives.parquet",
            filters=[("epsilon_index", "=", epsilon_index), ("bar", "=", bar)],
        )
        if table.num_rows == 0:
            return None
        start = table.column("start").to_numpy()
        end = table.column("end").to_numpy()
        rows = np.flatnonzero((start <= step) & (step <= end))
        simplices = table.column("simplex").to_pylist()
        return [simplices[i] for i in rows]

    def individuals(self) -> tuple[IntArray, IntArray, FloatArray]:
        """First step, last step and (analysed) objective vector of every individual."""
        table = pq.read_table(self._directory / "individuals.parquet")
        f_columns = sorted(
            (c for c in table.column_names if c.startswith("f_")), key=lambda c: int(c[2:])
        )
        points = np.column_stack([table.column(c).to_numpy() for c in f_columns])
        return (
            table.column("first_step").to_numpy().astype(np.intp),
            table.column("last_step").to_numpy().astype(np.intp),
            points.astype(np.float64),
        )


def filter_bars(table: pa.Table, min_lifetime: int) -> pa.Table:
    lifetime = pc.subtract(table.column("death"), table.column("birth"))
    return table.filter(pc.greater_equal(lifetime, min_lifetime))
