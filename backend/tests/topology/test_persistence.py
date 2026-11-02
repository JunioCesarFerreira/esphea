import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays

from esphea.topology.diagram import PersistenceDiagram
from esphea.topology.distances import (
    BottleneckDistance,
    WassersteinDistance,
    diameter,
    hausdorff_distance,
    nearest_neighbour_distances,
)
from esphea.topology.persistence import VietorisRips
from esphea.topology.summaries import betti_curve, persistent_entropy, total_persistence

RIPS = VietorisRips()


def circle(n: int, radius: float = 1.0) -> np.ndarray:
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return radius * np.column_stack((np.cos(angles), np.sin(angles)))


def two_clusters(gap: float) -> np.ndarray:
    rng = np.random.default_rng(0)
    left = rng.normal(scale=0.01, size=(20, 2))
    right = rng.normal(scale=0.01, size=(20, 2)) + np.array([gap, 0.0])
    return np.vstack((left, right))


def test_circle_has_one_persistent_loop() -> None:
    diagram = RIPS.compute(circle(60), max_dimension=1, max_epsilon=3.0)
    lifetimes = diagram.lifetimes(1)
    index = int(np.argmax(lifetimes))
    longest = diagram.bars[1][index]
    assert np.all(np.delete(lifetimes, index) < 0.05)  # any other loop is noise
    assert longest[0] == pytest.approx(2 * np.sin(np.pi / 60), abs=1e-6)  # birth: neighbour edge
    assert longest[1] == pytest.approx(np.sqrt(3), abs=0.05)  # death: inscribed triangle
    assert not diagram.truncated[1].any()


def test_components_merge_at_the_gap_between_clusters() -> None:
    clusters = two_clusters(gap=5.0)
    diagram = RIPS.compute(clusters, max_dimension=0, max_epsilon=10.0)
    deaths = np.sort(diagram.bars[0][:, 1])
    assert deaths[-2] == pytest.approx(5.0, abs=0.1)  # the two clusters merge
    assert deaths[-3] < 0.1  # within-cluster merges
    assert diagram.truncated[0].sum() == 1  # the essential class


def test_truncation_caps_features_alive_at_max_epsilon() -> None:
    clusters = two_clusters(gap=5.0)
    diagram = RIPS.compute(clusters, max_dimension=1, max_epsilon=1.0)
    assert diagram.truncated[0].sum() == 2
    assert np.all(diagram.bars[0][:, 1] <= 1.0)
    assert np.all(np.isfinite(diagram.bars[0]))


def test_from_intervals_rejects_nothing_and_keeps_dimensions() -> None:
    diagram = PersistenceDiagram.from_intervals([np.array([[0, np.inf]]), np.empty((0, 2))], 2.0)
    assert diagram.max_dimension == 1
    np.testing.assert_array_equal(diagram.bars[0], [[0.0, 2.0]])
    assert diagram.bars[1].shape == (0, 2)


@pytest.mark.parametrize("distance", [BottleneckDistance(), WassersteinDistance(1)])
def test_metric_basics(distance: BottleneckDistance | WassersteinDistance) -> None:
    a = np.array([[0.0, 1.0], [0.2, 0.5]])
    b = np.array([[0.0, 1.2]])
    assert distance(a, a) == pytest.approx(0.0)
    assert distance(a, b) == pytest.approx(distance(b, a))
    assert distance(a, b) > 0
    assert distance(np.empty((0, 2)), np.empty((0, 2))) == 0.0


def test_known_distances() -> None:
    a = np.array([[0.0, 1.0], [0.0, 0.4]])
    b = np.array([[0.0, 1.1]])
    # best matching: (0,1)<->(0,1.1) costs 0.1, (0,0.4) to the diagonal costs 0.2 (L-inf)
    assert BottleneckDistance()(a, b) == pytest.approx(0.2)
    assert WassersteinDistance(1)(a, b) == pytest.approx(0.3, rel=1e-3)


@settings(max_examples=25, deadline=None)
@given(
    points=arrays(np.float64, (25, 3), elements=st.floats(0, 1)),
    noise=arrays(np.float64, (25, 3), elements=st.floats(-0.05, 0.05)),
)
def test_stability_theorem(points: np.ndarray, noise: np.ndarray) -> None:
    """bottleneck(D(X), D(Y)) <= 2 * hausdorff(X, Y) in every dimension."""
    other = points + noise
    first = RIPS.compute(points, max_dimension=1, max_epsilon=2.0)
    second = RIPS.compute(other, max_dimension=1, max_epsilon=2.0)
    bound = 2 * hausdorff_distance(points, other) + 1e-9
    for k in (0, 1):
        assert BottleneckDistance()(first.bars[k], second.bars[k]) <= bound


def test_betti_curve_counts_alive_features() -> None:
    bars = np.array([[0.0, 1.0], [0.0, 2.0], [0.5, 2.0]])
    truncated = np.array([False, False, True])
    grid = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
    np.testing.assert_array_equal(betti_curve(bars, truncated, grid), [2, 3, 2, 2, 1])


def test_scalar_summaries() -> None:
    bars = np.array([[0.0, 1.0], [0.0, 1.0]])
    assert total_persistence(bars) == 2.0
    assert persistent_entropy(bars) == pytest.approx(np.log(2))
    assert persistent_entropy(np.empty((0, 2))) == 0.0


def test_point_cloud_measures() -> None:
    points = np.array([[0.0, 0.0], [3.0, 4.0], [0.0, 1.0]])
    assert diameter(points) == pytest.approx(5.0)
    np.testing.assert_allclose(nearest_neighbour_distances(points), [1.0, np.sqrt(18), 1.0])
    assert hausdorff_distance(points, points[:2]) == pytest.approx(1.0)
