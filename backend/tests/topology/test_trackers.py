import numpy as np
import pytest
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from esphea.topology.trackers import (
    ZIGZAG_METHOD,
    Resolution,
    TrackerMethod,
    agreement,
    compare_with_zigzag,
    matched,
    summarize,
    track_niches,
)
from esphea.topology.zigzag import ZigzagSequence, compute_zigzag

BUDGET = 1_000_000


def on_a_line(
    xs: list[float], first: list[int], last: list[int], generations: int
) -> ZigzagSequence:
    points = np.column_stack((xs, np.zeros(len(xs))))
    return ZigzagSequence(points, np.array(first), np.array(last), generations)


def as_set(bars: np.ndarray) -> list[tuple[int, int]]:
    return sorted((int(b), int(d)) for b, d in bars)


def zigzag_h0(sequence: ZigzagSequence, epsilon: float) -> np.ndarray:
    bars = compute_zigzag(sequence, epsilon, 0, max_simplices=BUDGET).bars
    return np.array([(b.birth, b.death) for b in bars], dtype=np.intp).reshape(-1, 2)


def split_then_vanish() -> ZigzagSequence:
    """P_0 = {0, 1}; offspring 2-4 extend the niche; removing 1 at P_1 splits it in
    {0} (the oldest individual) and {2, 3, 4} (the largest fragment); {0} is removed
    at P_2, and offspring 5 is a niche of R_2 only."""
    return on_a_line(
        [0.0, 0.5, 1.0, 1.5, 2.0, 3.0],
        first=[0, 0, 1, 1, 1, 3],
        last=[3, 1, 4, 4, 4, 3],
        generations=2,
    )


def test_split_rules_and_what_the_survivor_tracker_misses() -> None:
    sequence = split_then_vanish()
    bars = track_niches(sequence, 0.6)
    # the largest fragment keeps the bar: here this is also the zigzag pairing
    assert as_set(bars[TrackerMethod.T1]) == [(0, 5), (2, 4), (3, 4)]
    assert as_set(zigzag_h0(sequence, 0.6)) == [(0, 5), (2, 4), (3, 4)]
    # the oldest individual keeps the bar: same events, other pairing
    assert as_set(bars[TrackerMethod.T1O]) == [(0, 4), (2, 5), (3, 4)]
    # survivors only: the bar of {2, 3, 4} starts at P_1, and the niche of R_2 is unseen
    assert as_set(bars[TrackerMethod.T2]) == [(0, 4), (2, 5)]


def test_a_merge_seen_one_step_late_matches_by_generation() -> None:
    # two niches of P_0 bridged by an offspring in R_1 (step 1) that survives
    sequence = on_a_line([0.0, 1.0, 0.5], first=[0, 0, 1], last=[2, 2, 2], generations=1)
    zigzag = zigzag_h0(sequence, 0.6)
    assert as_set(zigzag) == [(0, 1), (0, 3)]
    bars = track_niches(sequence, 0.6)
    assert as_set(bars[TrackerMethod.T1]) == as_set(zigzag)
    t2 = bars[TrackerMethod.T2]
    assert as_set(t2) == [(0, 2), (0, 3)]  # the merge is dated at P_1
    assert agreement(zigzag, t2, Resolution.STEP) == 0.5
    assert agreement(zigzag, t2, Resolution.GENERATION) == 1.0
    order = np.argsort(t2[:, 1])
    assert matched(t2[order], zigzag, Resolution.STEP).tolist() == [False, True]
    assert matched(t2[order], zigzag, Resolution.GENERATION).tolist() == [True, True]


def random_sequence(seed: int, generations: int = 8, n: int = 14) -> ZigzagSequence:
    """A toy evolutionary process in the plane with random survival."""
    rng = np.random.default_rng(seed)
    points = list(rng.random((n, 2)))
    first, last = [0] * n, [0] * n
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


def n_components(points: np.ndarray, epsilon: float) -> int:
    pairs = cKDTree(points).query_pairs(epsilon, output_type="ndarray")
    n = len(points)
    graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    return int(connected_components(graph, directed=False)[0])


def alive(bars: np.ndarray, n_steps: int) -> np.ndarray:
    count = np.zeros(n_steps, dtype=int)
    for birth, death in bars:
        count[birth:death] += 1
    return count


@pytest.mark.parametrize("seed", range(6))
def test_every_tracker_follows_the_components_of_the_sets_it_sees(seed: int) -> None:
    sequence = random_sequence(seed)
    epsilon = 0.25
    expected = [
        n_components(sequence.points[sequence.members(k)], epsilon) for k in range(sequence.n_steps)
    ]
    bars = track_niches(sequence, epsilon)
    for method in (TrackerMethod.T1, TrackerMethod.T1O):
        np.testing.assert_array_equal(alive(bars[method], sequence.n_steps), expected)
    # the survivor tracker only sees the populations P_t (even steps)
    np.testing.assert_array_equal(
        alive(bars[TrackerMethod.T2], sequence.n_steps)[::2], expected[::2]
    )
    assert all(birth % 2 == 0 for birth, _ in bars[TrackerMethod.T2])


@pytest.mark.parametrize("seed", range(6))
def test_full_trackers_have_the_zigzag_events_but_not_always_its_pairing(seed: int) -> None:
    sequence = random_sequence(seed)
    zigzag = zigzag_h0(sequence, 0.25)
    bars = track_niches(sequence, 0.25)
    for method in (TrackerMethod.T1, TrackerMethod.T1O):
        for column in (0, 1):  # births and deaths per step
            np.testing.assert_array_equal(
                np.bincount(bars[method][:, column], minlength=sequence.n_steps + 1),
                np.bincount(zigzag[:, column], minlength=sequence.n_steps + 1),
            )


def test_summary_counts_and_lifetimes() -> None:
    zigzag = np.array([[0, 9], [1, 3], [2, 4], [4, 6]])
    tracker = np.array([[0, 9], [1, 3], [2, 6], [4, 4 + 1]])
    summary = summarize("t1", tracker, zigzag, n_steps=9, long_lifetime=4)
    assert summary.n_bars == 4
    assert summary.n_long == 2  # lifetimes 9 and 4
    assert summary.median_lifetime == 2.0  # finite lifetimes 2, 4, 1
    assert summary.at_least[:5] == [4, 3, 2, 2, 1]
    assert len(summary.at_least) == 9
    assert summary.agreement_step == 0.5
    assert summary.long_agreement_step == 1.0  # the only long zigzag bar is (0, 9)


def test_comparison_puts_the_zigzag_first_as_its_own_reference() -> None:
    sequence = split_then_vanish()
    zigzag = zigzag_h0(sequence, 0.6)
    trackers = {m.value: b for m, b in track_niches(sequence, 0.6).items()}
    rows = compare_with_zigzag(zigzag, trackers, sequence.n_steps, long_lifetime=2)
    assert [r.method for r in rows] == [ZIGZAG_METHOD, "t1", "t1o", "t2"]
    assert rows[0].agreement_step == rows[0].long_agreement_step == 1.0
    assert rows[1].agreement_step == 1.0
    assert rows[2].agreement_step == pytest.approx(1 / 3)  # only the niche of R_2
    assert rows[3].agreement_step == 0.0
    assert rows[3].n_bars == 2
    assert agreement(np.zeros((0, 2), dtype=np.intp), zigzag, Resolution.STEP) is None
