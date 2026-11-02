from pathlib import Path

import numpy as np
import pytest

from esphea.algorithms import NSGA2
from esphea.core import AlgorithmObserver, GenerationRecord, MaxGenerations, Population
from esphea.experiments.observers import SnapshotObserver
from esphea.experiments.storage import SnapshotReader, SnapshotWriter
from esphea.problems import DTLZ2


class Capture(AlgorithmObserver):
    def __init__(self) -> None:
        self.initial: Population | None = None
        self.records: dict[int, GenerationRecord] = {}

    def on_start(self, initial: Population) -> None:
        self.initial = initial

    def on_generation(self, record: GenerationRecord) -> None:
        self.records[record.generation] = record


def run_with_snapshots(
    tmp_path: Path, dtlz2: DTLZ2, *, n_gen: int, every: int, per_part: int
) -> tuple[Capture, Path]:
    directory = tmp_path / "run"
    writer = SnapshotWriter(
        directory, n_var=dtlz2.n_var, n_obj=dtlz2.n_obj, generations_per_part=per_part
    )
    capture = Capture()
    NSGA2(dtlz2, pop_size=20).run(
        MaxGenerations(n_gen),
        np.random.default_rng(0),
        [capture, SnapshotObserver(writer, every=every)],
    )
    return capture, directory


def test_roundtrip_of_a_generation(tmp_path: Path, dtlz2: DTLZ2) -> None:
    capture, directory = run_with_snapshots(tmp_path, dtlz2, n_gen=6, every=1, per_part=4)
    reader = SnapshotReader(directory)
    assert reader.generations() == list(range(7))
    assert len(list(directory.glob("part-*.parquet"))) == 2

    record = capture.records[3]
    snapshot = reader.read(3, decision_variables=True)
    assert snapshot.offspring is not None
    np.testing.assert_array_equal(snapshot.population.F, record.population.F)
    np.testing.assert_array_equal(snapshot.offspring.X, record.offspring.X)
    np.testing.assert_array_equal(snapshot.offspring.parents, record.offspring_parents)
    np.testing.assert_array_equal(snapshot.offspring.mutated, record.mutated)
    np.testing.assert_array_equal(snapshot.population.times_selected, record.times_selected())
    survived = np.concatenate((snapshot.population.survived, snapshot.offspring.survived))
    np.testing.assert_array_equal(survived, record.survived_mask())


def test_initial_generation_has_no_offspring(tmp_path: Path, dtlz2: DTLZ2) -> None:
    capture, directory = run_with_snapshots(tmp_path, dtlz2, n_gen=2, every=1, per_part=10)
    snapshot = SnapshotReader(directory).read(0)
    assert snapshot.offspring is None
    assert snapshot.population.X is None  # not requested
    assert capture.initial is not None
    np.testing.assert_array_equal(snapshot.population.F, capture.initial.F)


def test_every_n_keeps_the_last_generation(tmp_path: Path, dtlz2: DTLZ2) -> None:
    _, directory = run_with_snapshots(tmp_path, dtlz2, n_gen=7, every=3, per_part=10)
    assert SnapshotReader(directory).generations() == [0, 3, 6, 7]


def test_missing_generation(tmp_path: Path, dtlz2: DTLZ2) -> None:
    _, directory = run_with_snapshots(tmp_path, dtlz2, n_gen=2, every=1, per_part=10)
    with pytest.raises(KeyError):
        SnapshotReader(directory).read(99)
