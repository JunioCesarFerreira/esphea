from itertools import combinations
from pathlib import Path

import dionysus
import numpy as np
import pytest
from pydantic import ValidationError
from ripser import ripser
from scipy.sparse.csgraph import connected_components
from scipy.spatial.distance import pdist, squareform

from esphea.algorithms import NSGA2
from esphea.core import MaxGenerations
from esphea.experiments.observers import SnapshotObserver
from esphea.experiments.storage import SnapshotReader, SnapshotWriter
from esphea.problems import DTLZ2
from esphea.topology.clouds import Identity
from esphea.topology.config import ZIGZAG_ANALYSIS, ZigzagAnalysisConfig, parse_analysis_config
from esphea.topology.zigzag import (
    Cause,
    MiddleComplex,
    SimplexBudgetExceededError,
    ZigzagResult,
    ZigzagSequence,
    complex_members,
    compute_zigzag,
    is_r_step,
    zigzag_complex,
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


# --- union complexes W_t = VR(P_{t-1} + P_t) ---------------------------------------------

UNION = MiddleComplex.UNION

Simplex = tuple[int, ...]


def rips_cliques(
    points: np.ndarray, members: np.ndarray, epsilon: float, size: int
) -> set[Simplex]:
    """Simplices of VR(members) with up to ``size`` vertices, by brute force."""
    close = squareform(pdist(points[members])) <= epsilon
    return {
        tuple(int(members[i]) for i in c)
        for k in range(1, size + 1)
        for c in combinations(range(len(members)), k)
        if all(close[a, b] for a, b in combinations(c, 2))
    }


def union_complexes(
    sequence: ZigzagSequence, epsilon: float, size: int, *, union_of_points: bool = True
) -> list[set[Simplex]]:
    """VR(P_t) at P steps and, at R steps, VR(P_{t-1} + P_t), by brute force.

    With ``union_of_points=False`` the R steps take the union of the two complexes
    VR(P_{t-1}) + VR(P_t) instead (the complex that was not adopted).
    """
    members = [sequence.members(2 * t) for t in range(sequence.n_generations + 1)]
    p = [rips_cliques(sequence.points, m, epsilon, size) for m in members]
    complexes = []
    for k in range(sequence.n_steps):
        t = k // 2
        if k % 2 == 0:
            complexes.append(p[t])
        elif not union_of_points:
            complexes.append(p[t] | p[t + 1])
        else:
            union = np.union1d(members[t], members[t + 1])
            complexes.append(rips_cliques(sequence.points, union, epsilon, size))
    return complexes


def f2_rank(columns: list[set[Simplex]]) -> int:
    """Rank over F2 of the vectors given as sets of coordinates (simplices)."""
    pivots: dict[Simplex, set[Simplex]] = {}
    for column in columns:
        reduced = set(column)
        while reduced and max(reduced) in pivots:
            reduced ^= pivots[max(reduced)]
        if reduced:
            pivots[max(reduced)] = reduced
    return len(pivots)


def betti_0(complex_: set[Simplex]) -> int:
    vertices = sorted(s[0] for s in complex_ if len(s) == 1)
    index = {v: i for i, v in enumerate(vertices)}
    edges = np.array(
        [(index[a], index[b]) for a, b in (s for s in complex_ if len(s) == 2)], dtype=np.intp
    ).reshape(-1, 2)
    return components(len(vertices), edges)


def betti_1(complex_: set[Simplex]) -> int:
    edges = [s for s in complex_ if len(s) == 2]
    triangles = [s for s in complex_ if len(s) == 3]
    rank_1 = f2_rank([{(a,), (b,)} for a, b in edges])
    rank_2 = f2_rank([set(combinations(t, 2)) for t in triangles])
    return len(edges) - rank_1 - rank_2


def components(n: int, edges: np.ndarray) -> int:
    graph = np.zeros((n, n))
    graph[edges[:, 0], edges[:, 1]] = 1
    return int(connected_components(graph, directed=False)[0])


def zigzag_bars(complexes: list[set[Simplex]], dimension: int) -> list[tuple[int, int]]:
    """Zigzag barcode of an arbitrary sequence of complexes (independent of zigzag_complex)."""
    simplices = sorted(set().union(*complexes), key=lambda s: (len(s), s))
    times = []
    for simplex in simplices:
        present = [k for k, c in enumerate(complexes) if simplex in c]
        runs = [k for i, k in enumerate(present) if i == 0 or present[i - 1] != k - 1]
        ends = [
            k + 1 for i, k in enumerate(present) if i == len(present) - 1 or present[i + 1] != k + 1
        ]
        times.append([t for run in zip(runs, ends, strict=True) for t in run])
    cone = dionysus.fast_zigzag([list(s) for s in simplices], times)
    diagrams = dionysus.init_zigzag_diagrams(dionysus.homology_persistence(cone), cone)
    n = len(complexes)
    found = diagrams[dimension].values() if dimension < len(diagrams) else []
    return sorted(
        (int(p.birth), n if np.isinf(p.death) else min(int(p.death), n))
        for diagram in found
        for p in diagram
    )


def bars_of(result: ZigzagResult, dimension: int) -> list[tuple[int, int]]:
    return sorted((b.birth, b.death) for b in result.bars if b.dimension == dimension)


def events_of(result: ZigzagResult, dimension: int) -> list[tuple[int, int, Cause, Cause]]:
    return sorted(
        (b.birth, b.death, b.birth_cause, b.death_cause)
        for b in result.bars
        if b.dimension == dimension
    )


def alive_counts(bars: list[tuple[int, int]], n_steps: int) -> np.ndarray:
    alive = np.zeros(n_steps, dtype=int)
    for birth, death in bars:
        alive[birth:death] += 1
    return alive


@pytest.mark.parametrize("seed", range(8))
def test_union_is_the_zigzag_of_the_parents_and_the_survivors(seed: int) -> None:
    """P_{t-1} -> VR(P_{t-1} + P_t) <- P_t, against an independent construction."""
    sequence = random_sequence(np.random.default_rng(seed))
    epsilon = 0.3
    rips = compute_zigzag(sequence, epsilon, 1, max_simplices=BUDGET)
    union = compute_zigzag(sequence, epsilon, 1, max_simplices=BUDGET, middle=UNION)
    complexes = union_complexes(sequence, epsilon, 3)
    for dimension in (0, 1):
        assert bars_of(union, dimension) == zigzag_bars(complexes, dimension)
    # and, independently of Dionysus, the features alive at every step
    n = sequence.n_steps
    for dimension, betti in ((0, betti_0), (1, betti_1)):
        np.testing.assert_array_equal(
            alive_counts(bars_of(union, dimension), n), [betti(c) for c in complexes]
        )
    assert union.n_simplices == len(set().union(*complexes))
    assert union.n_simplices < rips.n_simplices


@pytest.mark.parametrize("seed", range(4))
def test_union_leaves_out_only_the_offspring_discarded_at_once(seed: int) -> None:
    sequence = random_sequence(np.random.default_rng(seed))
    for step in range(sequence.n_steps):
        members = sequence.members(step)
        np.testing.assert_array_equal(sequence.vertices(step, MiddleComplex.RIPS), members)
        if is_r_step(step):
            kept = np.union1d(sequence.members(step - 1), sequence.members(step + 1))
            np.testing.assert_array_equal(sequence.vertices(step, UNION), kept)
            assert len(kept) < len(members)  # random survival discards some offspring
        else:
            np.testing.assert_array_equal(sequence.vertices(step, UNION), members)
        np.testing.assert_array_equal(
            complex_members(sequence.first, sequence.last, step, UNION),
            sequence.vertices(step, UNION),
        )
    simplices, _ = zigzag_complex(sequence, 0.3, 1, max_simplices=BUDGET, middle=UNION)
    vertices = {v for simplex in simplices for v in simplex}
    discarded = {
        i for i in range(len(sequence.first)) if sequence.first[i] == sequence.last[i] != 0
    }
    assert discarded
    assert not vertices & discarded


@pytest.mark.parametrize(("n", "epsilon", "seed"), [(12, 1.3, 3), (16, 1.3, 5), (16, 1.3, 6)])
def test_union_voids_are_those_of_the_parents_and_the_survivors(
    n: int, epsilon: float, seed: int
) -> None:
    """Individuals on the unit sphere (cases where the voids of rips and union differ)."""
    rng = np.random.default_rng(seed)
    genealogy = random_sequence(rng, generations=3, n=n)
    directions = rng.normal(size=(genealogy.points.shape[0], 3))
    sequence = ZigzagSequence(
        directions / np.linalg.norm(directions, axis=1, keepdims=True),
        genealogy.first,
        genealogy.last,
        genealogy.n_generations,
    )
    rips = compute_zigzag(sequence, epsilon, 2, max_simplices=BUDGET)
    union = compute_zigzag(sequence, epsilon, 2, max_simplices=BUDGET, middle=UNION)
    assert bars_of(union, 2) != bars_of(rips, 2)
    complexes = union_complexes(sequence, epsilon, 4)
    for dimension in (0, 1, 2):
        assert bars_of(union, dimension) == zigzag_bars(complexes, dimension)


def test_a_void_filled_only_by_a_discarded_offspring_persists_in_the_union() -> None:
    """The hollow octahedron is a sphere at 1.5; an offspring at its centre cones it in R_1."""
    axes = np.vstack((np.eye(3), -np.eye(3)))
    points = np.vstack((axes, [[0.0, 0.0, 0.0]]))
    sequence = ZigzagSequence(points, np.array([0] * 6 + [1]), np.array([2] * 6 + [1]), 1)
    rips = compute_zigzag(sequence, 1.5, 2, max_simplices=BUDGET)
    union = compute_zigzag(sequence, 1.5, 2, max_simplices=BUDGET, middle=UNION)
    assert bars_of(rips, 2) == [(0, 1), (2, 3)]
    assert bars_of(union, 2) == [(0, 3)]
    assert bars_of(union, 1) == bars_of(rips, 1) == []
    assert bars_of(union, 0) == bars_of(rips, 0) == [(0, 3)]


def square_with_a_discarded_centre() -> ZigzagSequence:
    """A square loop in P_0 and P_1; an offspring at its centre fills it in R_1 only."""
    points = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.5, 0.5]])
    return ZigzagSequence(points, np.array([0, 0, 0, 0, 1]), np.array([2, 2, 2, 2, 1]), 1)


def test_a_hole_filled_only_by_a_discarded_offspring_persists_in_the_union() -> None:
    sequence = square_with_a_discarded_centre()
    rips = compute_zigzag(sequence, 1.1, 1, max_simplices=BUDGET, representatives=5)
    union = compute_zigzag(sequence, 1.1, 1, max_simplices=BUDGET, middle=UNION, representatives=5)
    assert events_of(rips, 1) == [
        (0, 1, Cause.INITIAL, Cause.VARIATION),  # filled by the offspring
        (2, 3, Cause.SELECTION, Cause.END),  # reopened when it is discarded
    ]
    [loop] = [i for i, b in enumerate(union.bars) if b.dimension == 1]
    assert (union.bars[loop].birth, union.bars[loop].death) == (0, 3)
    [segment] = union.representatives[loop]
    assert (segment.start, segment.end) == (0, 2)
    assert segment.simplices == ((0, 1), (0, 3), (1, 2), (2, 3))
    assert bars_of(union, 0) == bars_of(rips, 0) == [(0, 3)]


def test_a_loop_handed_over_to_an_offspring_keeps_one_bar() -> None:
    """A hexagonal loop whose vertex 0 is replaced by a nearby offspring (6) that survives.

    In R_1 the triangles (0, 6, 1) and (0, 6, 5) make the two loops homologous. Through the
    union of the two complexes, without the edge 0-6 (discarded parent, surviving
    offspring), they would be independent: the loop would die by selection and be born
    again by variation.
    """
    angles = np.linspace(0, 2 * np.pi, 6, endpoint=False)
    points = np.vstack((np.column_stack((np.cos(angles), np.sin(angles))), [[1.05, 0.05]]))
    first = np.array([0] * 6 + [1])
    last = np.array([1] + [2] * 5 + [2])  # 0 is discarded at t = 1, 6 survives
    sequence = ZigzagSequence(points, first, last, 1)
    rips = compute_zigzag(sequence, 1.1, 1, max_simplices=BUDGET)
    union = compute_zigzag(sequence, 1.1, 1, max_simplices=BUDGET, middle=UNION)
    assert bars_of(rips, 1) == bars_of(union, 1) == [(0, 3)]
    # the loop through the parent (steps 0-1) and the loop through the offspring (1-2)
    assert zigzag_bars(union_complexes(sequence, 1.1, 3, union_of_points=False), 1) == [
        (0, 2),
        (1, 3),
    ]


def test_a_discarded_offspring_joins_two_niches_in_rips_only() -> None:
    """Two niches joined in R_1 by an offspring that selection discards at once."""
    points = np.array([[0.0, 0.0], [1.6, 0.0], [0.8, 0.0]])
    sequence = ZigzagSequence(points, np.array([0, 0, 1]), np.array([2, 2, 1]), 1)
    rips = compute_zigzag(sequence, 1.0, 0, max_simplices=BUDGET)
    union = compute_zigzag(sequence, 1.0, 0, max_simplices=BUDGET, middle=UNION)
    assert events_of(rips, 0) == [
        (0, 1, Cause.INITIAL, Cause.VARIATION),
        (0, 3, Cause.INITIAL, Cause.END),
        (2, 3, Cause.SELECTION, Cause.END),
    ]
    assert events_of(union, 0) == [(0, 3, Cause.INITIAL, Cause.END)] * 2


@pytest.mark.parametrize("middle", [MiddleComplex.BRIDGE, MiddleComplex.BRIDGE_UNION])
def test_retired_complexes_are_not_computed(middle: MiddleComplex) -> None:
    assert middle.retired
    sequence = square_with_a_discarded_centre()
    with pytest.raises(ValueError, match="retired"):
        compute_zigzag(sequence, 1.1, 1, max_simplices=BUDGET, middle=middle)


def test_retired_complexes_load_from_storage_only() -> None:
    settings = {"epsilons": [0.1], "middle": "bridge_union"}
    with pytest.raises(ValidationError, match="retired"):
        ZigzagAnalysisConfig.model_validate(settings)
    stored = parse_analysis_config(ZIGZAG_ANALYSIS, settings)
    assert isinstance(stored, ZigzagAnalysisConfig)
    assert stored.middle == MiddleComplex.BRIDGE_UNION
    assert ZigzagAnalysisConfig.model_validate({**settings, "middle": "union"}).middle == UNION
