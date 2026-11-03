"""Columnar storage of generation snapshots (Apache Parquet).

Each stored generation contributes one row per individual of ``P_t + Q_t``
(``P_0`` alone for generation 0). Rows are buffered and flushed into
self-contained, zstd-compressed part files every few generations, so memory
stays bounded and completed parts are readable while the run is in progress.
Parts are written to a temporary name and renamed atomically. Each execution
attempt of a run has its own directory (:func:`snapshot_directory`).

Row layout (see :data:`ROLE_POPULATION`, :data:`ROLE_OFFSPRING`):

========================  ============================================================
column                    meaning
========================  ============================================================
generation (int32)        generation index ``t`` (0 = initial population)
individual_id (int64)     run-unique identity of the individual (schema >= 2)
role (int8)               0 = parent pool ``P_t``, 1 = offspring ``Q_t``
index (int32)             position within its role
survived (bool)           selected into ``P_{t+1}``
rank (int32)              non-domination rank in the survival (-1 if discarded)
times_selected (int16)    matings the individual took part in (population rows)
parent_a/parent_b (int32) indices into ``P_t`` (offspring rows, -1 otherwise)
mutated (bool)            mutation changed the offspring
x_0..x_{n-1}              decision variables (optional)
f_0..f_{m-1}              objectives
========================  ============================================================
"""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from esphea.core.population import Population
from esphea.core.records import GenerationRecord
from esphea.core.types import AnyArray, BoolArray, FloatArray, IntArray

ROLE_POPULATION = 0
ROLE_OFFSPRING = 1
SCHEMA_VERSION = 2
"""1: initial layout; 2: adds ``individual_id``."""
_META_FILE = "meta.json"
_PART_GLOB = "part-*.parquet"


def snapshot_directory(root: Path, run_id: uuid.UUID, attempt: int) -> Path:
    """Where ``attempt`` of a run stores its snapshots: ``<root>/<run-id>/attempt-<n>``.

    Each attempt writes to its own directory, so a worker that lost a run can
    never mix its files with those of the retry.
    """
    return root / str(run_id) / f"attempt-{attempt}"


def _x_columns(n_var: int) -> list[str]:
    return [f"x_{i}" for i in range(n_var)]


def _f_columns(n_obj: int) -> list[str]:
    return [f"f_{i}" for i in range(n_obj)]


class SnapshotWriter:
    """Streams generation snapshots of one run to ``directory``."""

    def __init__(
        self,
        directory: Path,
        *,
        n_var: int,
        n_obj: int,
        precision: Literal["float32", "float64"] = "float64",
        decision_variables: bool = True,
        generations_per_part: int = 20,
    ) -> None:
        if generations_per_part < 1:
            raise ValueError("generations_per_part must be positive")
        self._directory = directory
        self._n_var = n_var
        self._n_obj = n_obj
        self._dtype = np.float32 if precision == "float32" else np.float64
        self._decision_variables = decision_variables
        self._generations_per_part = generations_per_part
        self._buffer: list[pa.RecordBatch] = []
        self._buffered_generations = 0
        self._part = 0
        directory.mkdir(parents=True, exist_ok=True)
        meta = {
            "schema_version": SCHEMA_VERSION,
            "n_var": n_var,
            "n_obj": n_obj,
            "precision": precision,
            "decision_variables": decision_variables,
        }
        (directory / _META_FILE).write_text(json.dumps(meta))

    def write_initial(self, population: Population, ids: IntArray) -> None:
        n = len(population)
        self._append(
            generation=0,
            ids=ids,
            role=np.full(n, ROLE_POPULATION, dtype=np.int8),
            index=np.arange(n, dtype=np.int32),
            survived=np.ones(n, dtype=np.bool_),
            rank=self._rank_of(population, n),
            times_selected=np.zeros(n, dtype=np.int16),
            parents=np.full((n, 2), -1, dtype=np.int32),
            mutated=np.zeros(n, dtype=np.bool_),
            X=population.X,
            F=population.F,
        )

    def write_generation(
        self, record: GenerationRecord, population_ids: IntArray, offspring_ids: IntArray
    ) -> None:
        n_pop, n_off = len(record.population), len(record.offspring)
        merged = record.merged()
        rank = np.full(n_pop + n_off, -1, dtype=np.int32)
        if "rank" in record.survivors.attributes:
            rank[record.survivor_indices] = record.survivors.attribute("rank")
        parents = np.full((n_pop + n_off, 2), -1, dtype=np.int32)
        parents[n_pop:] = record.offspring_parents[:, :2]
        times_selected = np.zeros(n_pop + n_off, dtype=np.int16)
        times_selected[:n_pop] = record.times_selected()
        mutated = np.zeros(n_pop + n_off, dtype=np.bool_)
        mutated[n_pop:] = record.mutated
        self._append(
            generation=record.generation,
            ids=np.concatenate((population_ids, offspring_ids)),
            role=np.repeat(
                np.array([ROLE_POPULATION, ROLE_OFFSPRING], dtype=np.int8), [n_pop, n_off]
            ),
            index=np.concatenate((np.arange(n_pop), np.arange(n_off))).astype(np.int32),
            survived=record.survived_mask(),
            rank=rank,
            times_selected=times_selected,
            parents=parents,
            mutated=mutated,
            X=merged.X,
            F=merged.F,
        )

    def close(self) -> None:
        self._flush()

    @staticmethod
    def _rank_of(population: Population, n: int) -> IntArray:
        if "rank" in population.attributes:
            return population.attribute("rank").astype(np.int32)
        return np.full(n, -1, dtype=np.int32)

    def _append(
        self,
        *,
        generation: int,
        ids: IntArray,
        role: AnyArray,
        index: AnyArray,
        survived: BoolArray,
        rank: AnyArray,
        times_selected: AnyArray,
        parents: AnyArray,
        mutated: BoolArray,
        X: FloatArray,
        F: FloatArray,
    ) -> None:
        n = role.shape[0]
        columns: dict[str, AnyArray] = {
            "generation": np.full(n, generation, dtype=np.int32),
            "individual_id": ids.astype(np.int64),
            "role": role,
            "index": index,
            "survived": survived,
            "rank": rank,
            "times_selected": times_selected,
            "parent_a": parents[:, 0],
            "parent_b": parents[:, 1],
            "mutated": mutated,
        }
        if self._decision_variables:
            columns.update(zip(_x_columns(self._n_var), X.astype(self._dtype).T, strict=True))
        columns.update(zip(_f_columns(self._n_obj), F.astype(self._dtype).T, strict=True))
        self._buffer.append(pa.RecordBatch.from_pydict(columns))
        self._buffered_generations += 1
        if self._buffered_generations >= self._generations_per_part:
            self._flush()

    def _flush(self) -> None:
        if not self._buffer:
            return
        table = pa.Table.from_batches(self._buffer)
        final = self._directory / f"part-{self._part:05d}.parquet"
        temporary = final.with_suffix(".tmp")
        pq.write_table(table, temporary, compression="zstd")
        temporary.replace(final)
        self._part += 1
        self._buffer.clear()
        self._buffered_generations = 0


@dataclass(frozen=True, slots=True)
class SnapshotGroup:
    """Individuals of one role in a stored generation."""

    F: FloatArray
    X: FloatArray | None
    survived: BoolArray
    rank: IntArray
    times_selected: IntArray
    parents: IntArray
    mutated: BoolArray
    ids: IntArray | None = None  # run-unique identities (None for schema 1 runs)


@dataclass(frozen=True, slots=True)
class GenerationSnapshot:
    generation: int
    population: SnapshotGroup
    offspring: SnapshotGroup | None


class SnapshotReader:
    """Reads snapshots written by :class:`SnapshotWriter` (also during a run)."""

    def __init__(self, directory: Path) -> None:
        meta_path = directory / _META_FILE
        if not meta_path.exists():
            raise FileNotFoundError(f"no snapshots in {directory}")
        meta = json.loads(meta_path.read_text())
        self._directory = directory
        self.n_var: int = meta["n_var"]
        self.n_obj: int = meta["n_obj"]
        self.has_decision_variables: bool = meta["decision_variables"]
        self.has_individual_ids: bool = meta.get("schema_version", 1) >= 2

    def _dataset(self) -> ds.Dataset | None:
        parts = sorted(self._directory.glob(_PART_GLOB))
        if not parts:
            return None
        return ds.dataset([str(part) for part in parts], format="parquet")

    def generations(self) -> list[int]:
        dataset = self._dataset()
        if dataset is None:
            return []
        column = dataset.to_table(columns=["generation"]).column("generation")
        return [int(g) for g in pc.unique(column).to_numpy()]

    def _columns(self, want_x: bool) -> list[str]:
        columns = [
            "role", "survived", "rank", "times_selected", "parent_a", "parent_b", "mutated",
            *_f_columns(self.n_obj),
        ]  # fmt: skip
        if want_x:
            columns.extend(_x_columns(self.n_var))
        if self.has_individual_ids:
            columns.append("individual_id")
        return columns

    def read(self, generation: int, *, decision_variables: bool = False) -> GenerationSnapshot:
        dataset = self._dataset()
        if dataset is None:
            raise KeyError(f"generation {generation} is not stored")
        want_x = decision_variables and self.has_decision_variables
        table = dataset.to_table(
            columns=self._columns(want_x), filter=pc.field("generation") == generation
        )
        if table.num_rows == 0:
            raise KeyError(f"generation {generation} is not stored")
        return self._snapshot(generation, table, want_x)

    def iter_generations(self, *, decision_variables: bool = False) -> Iterator[GenerationSnapshot]:
        """Every stored generation in order, reading each part file once."""
        want_x = decision_variables and self.has_decision_variables
        columns = ["generation", *self._columns(want_x)]
        for part in sorted(self._directory.glob(_PART_GLOB)):
            table = pq.read_table(part, columns=columns)
            generations = table.column("generation").to_numpy()
            for generation in np.unique(generations):
                rows = table.filter(pa.array(generations == generation))
                yield self._snapshot(int(generation), rows, want_x)

    def _snapshot(self, generation: int, table: pa.Table, want_x: bool) -> GenerationSnapshot:
        role = table.column("role").to_numpy()

        def group(mask: BoolArray) -> SnapshotGroup:
            def col(name: str) -> AnyArray:
                return np.asarray(table.column(name).to_numpy())[mask]

            def matrix(names: list[str]) -> FloatArray:
                return np.column_stack([col(c) for c in names]).astype(np.float64)

            return SnapshotGroup(
                F=matrix(_f_columns(self.n_obj)),
                X=matrix(_x_columns(self.n_var)) if want_x else None,
                survived=col("survived").astype(np.bool_),
                rank=col("rank").astype(np.intp),
                times_selected=col("times_selected").astype(np.intp),
                parents=np.column_stack((col("parent_a"), col("parent_b"))).astype(np.intp),
                mutated=col("mutated").astype(np.bool_),
                ids=col("individual_id").astype(np.int64) if self.has_individual_ids else None,
            )

        offspring_mask = role == ROLE_OFFSPRING
        return GenerationSnapshot(
            generation=generation,
            population=group(role == ROLE_POPULATION),
            offspring=group(offspring_mask) if offspring_mask.any() else None,
        )
