from pathlib import Path

import numpy as np
import pytest
from ripser import ripser

from esphea.algorithms import NSGA2
from esphea.core import MaxGenerations
from esphea.experiments.observers import SnapshotObserver
from esphea.experiments.storage import SnapshotReader, SnapshotWriter
from esphea.problems import DTLZ2
from esphea.topology.clouds import Identity
from esphea.topology.zigzag import (
    Cause,
    SimplexBudgetExceededError,
    ZigzagSequence,
    compute_zigzag,
    is_r_step,
)

BUDGET = 1_000_000


def random_sequence(rng: np.random.Generator, generations: int = 6, n: int = 14) -> ZigzagSequence:
    """A toy evolutionary process in the plane with random survival."""
    points = list(rng.random((n, 2)))
    first = [0] * n
    last = [0] * n
    population = list(range(n))
    for t in range(1, generations + 1):
        parents = np.array(points)[rng.choice(population, n)]
        children = list(range(len(points), len(points) + n))
        points.extend(parents + rng.normal(scale=0.15, size=(n, 2)))
        first.extend([2 * t - 1] * n)
        last.extend([2 * t - 1] * n)
        candidates = population + children
        population = [int(i) for i in rng.choice(candidates, n, replace=False)]
        for i in candidates:
            last[i] = 2 * t if i in population else 2 * t - 1
    return ZigzagSequence(np.array(points), np.array(first), np.array(last), generations)


def betti_numbers(points: np.ndarray, epsilon: float, dimension: int) -> int:
    bars = ripser(points, maxdim=dimension, thresh=epsilon)["dgms"][dimension]
    return int(np.sum((bars[:, 0] <= epsilon) & (bars[:, 1] > epsilon)))


@pytest.mark.parametrize("seed", range(8))
def test_bars_alive_at_each_step_match_the_homology_of_that_step(seed: int) -> None:
    """The defining property of the zigzag barcode, checked against Ripser."""
    rng = np.random.default_rng(seed)
    sequence = random_sequence(rng)
    epsilon = 0.3
    result = compute_zigzag(sequence, epsilon, 1, max_simplices=BUDGET)
    for dimension in (0, 1):
        alive = np.zeros(sequence.n_steps, dtype=int)
        for bar in result.bars:
            if bar.dimension == dimension:
                alive[bar.birth : bar.death] += 1
        expected = [
            betti_numbers(sequence.points[sequence.members(k)], epsilon, dimension)
            for k in range(sequence.n_steps)
        ]
        np.testing.assert_array_equal(alive, expected)


@pytest.mark.parametrize("seed", range(4))
def test_causes_follow_the_arrows(seed: int) -> None:
    result = compute_zigzag(
        random_sequence(np.random.default_rng(seed)), 0.3, 1, max_simplices=BUDGET
    )
    for bar in result.bars:
        # Dionysus' interval type agrees with the arrow that caused each event
        if bar.birth == 0:
            assert bar.birth_cause == Cause.INITIAL
        else:
            assert (bar.kind[0] == "c") == (bar.birth_cause == Cause.VARIATION)
            assert is_r_step(bar.birth) == (bar.birth_cause == Cause.VARIATION)
        if bar.death < result.n_steps:
            assert (bar.kind[1] == "o") == (bar.death_cause == Cause.VARIATION)


def two_niches(survive_second: bool) -> ZigzagSequence:
    """Two far-apart individuals; the second niche is discarded at P_1 unless it survives."""
    points = np.array([[0.0, 0.0], [5.0, 0.0], [0.1, 0.0]])
    first = np.array([0, 0, 1])  # individual 2 is an offspring in R_1
    last = np.array([2, 2 if survive_second else 1, 2])
    return ZigzagSequence(points, first, last, 1)


def test_a_niche_wiped_out_by_selection() -> None:
    bars = compute_zigzag(two_niches(False), 1.0, 0, max_simplices=BUDGET).bars
    ended = sorted((b.birth, b.death, b.death_cause) for b in bars)
    assert ended == [(0, 2, Cause.SELECTION), (0, 3, Cause.END)]


def test_offspring_bridging_two_niches_kill_one_by_variation() -> None:
    points = np.array([[0.0, 0.0], [1.6, 0.0], [0.8, 0.0]])  # child in the middle
    sequence = ZigzagSequence(points, np.array([0, 0, 1]), np.array([2, 2, 2]), 1)
    bars = compute_zigzag(sequence, 1.0, 0, max_simplices=BUDGET).bars
    assert sorted((b.birth, b.death, b.death_cause) for b in bars) == [
        (0, 1, Cause.VARIATION),
        (0, 3, Cause.END),
    ]


def test_a_loop_persisting_across_generations_has_a_cycle_representative() -> None:
    angles = np.linspace(0, 2 * np.pi, 12, endpoint=False)
    ring = np.column_stack((np.cos(angles), np.sin(angles)))
    # the ring survives two generations; a far offspring appears and is discarded each time
    points = np.vstack((ring, [[5.0, 5.0], [6.0, 6.0]]))
    first = np.array([0] * 12 + [1, 3])
    last = np.array([4] * 12 + [1, 3])
    result = compute_zigzag(
        ZigzagSequence(points, first, last, 2), 0.6, 1, max_simplices=BUDGET, representatives=5
    )
    loops = [i for i, b in enumerate(result.bars) if b.dimension == 1]
    assert len(loops) == 1
    loop = result.bars[loops[0]]
    assert (loop.birth, loop.death, loop.death_cause) == (0, 5, Cause.END)
    [segment] = result.representatives[loops[0]]
    assert (segment.start, segment.end) == (0, 4)
    assert len(segment.simplices) == 12  # the twelve edges of the ring
    assert all(len(s) == 2 and max(s) < 12 for s in segment.simplices)


def test_budget_guard() -> None:
    sequence = random_sequence(np.random.default_rng(0))
    with pytest.raises(SimplexBudgetExceededError, match="smaller epsilon"):
        compute_zigzag(sequence, 5.0, 2, max_simplices=1000)


def test_sequence_from_snapshots(tmp_path: Path, dtlz2: DTLZ2) -> None:
    writer = SnapshotWriter(tmp_path, n_var=dtlz2.n_var, n_obj=3, generations_per_part=3)
    NSGA2(dtlz2, pop_size=16).run(
        MaxGenerations(5), np.random.default_rng(0), [SnapshotObserver(writer)]
    )
    sequence = ZigzagSequence.from_snapshots(SnapshotReader(tmp_path), Identity())
    assert sequence.n_generations == 5
    assert sequence.points.shape == (16 + 5 * 16, 3)
    for t in range(1, 6):
        assert sequence.members(2 * t - 1).shape == (32,)  # R_t = P_{t-1} + Q_t
        assert sequence.members(2 * t).shape == (16,)  # P_t
        assert set(sequence.members(2 * t)) <= set(sequence.members(2 * t - 1))
        assert set(sequence.members(2 * t - 2)) <= set(sequence.members(2 * t - 1))


def test_sparse_snapshots_are_rejected(tmp_path: Path, dtlz2: DTLZ2) -> None:
    writer = SnapshotWriter(tmp_path, n_var=dtlz2.n_var, n_obj=3)
    NSGA2(dtlz2, pop_size=8).run(
        MaxGenerations(4), np.random.default_rng(0), [SnapshotObserver(writer, every=2)]
    )
    with pytest.raises(ValueError, match="every generation"):
        ZigzagSequence.from_snapshots(SnapshotReader(tmp_path), Identity())


def test_representatives_are_skipped_above_their_budget() -> None:
    sequence = random_sequence(np.random.default_rng(1))
    result = compute_zigzag(
        sequence,
        0.3,
        1,
        max_simplices=BUDGET,
        representatives=5,
        max_representative_simplices=10,
    )
    assert result.representatives == {}
    assert result.representatives_skipped is not None
    assert "smaller epsilon" in result.representatives_skipped
    assert result.n_simplices > 10
    assert result.bars  # the barcode itself is still computed
