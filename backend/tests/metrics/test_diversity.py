import numpy as np
import pytest
from pymoo.indicators.spacing import SpacingIndicator
from scipy.spatial.distance import pdist

from esphea.core.population import Population
from esphea.metrics import DecisionInertia, GeneralizedSpread, MeanPairwiseDistance, Spacing

UNIT = (np.zeros(2), np.ones(2))


def population(F: np.ndarray, X: np.ndarray | None = None) -> Population:
    return Population(X=F.copy() if X is None else X, F=F)


def linear_front(n: int) -> np.ndarray:
    f1 = np.linspace(0.0, 1.0, n)
    return np.column_stack((f1, 1.0 - f1))


def test_spacing_by_hand() -> None:
    front = np.array([[0.0, 1.0], [0.1, 0.9], [0.5, 0.5], [1.0, 0.0]])
    # Manhattan nearest-neighbour distances 0.2, 0.2, 0.8, 1.0
    assert Spacing(*UNIT)(population(front), front) == pytest.approx(np.sqrt(0.51 / 3))


def test_spacing_matches_pymoo_up_to_the_denominator() -> None:
    front = np.random.default_rng(0).uniform(size=(30, 3))
    ours = Spacing(np.zeros(3), np.ones(3))(population(front), front)
    theirs = SpacingIndicator(pf=front)(front)  # pymoo divides by n, Schott by n - 1
    assert ours == pytest.approx(theirs * np.sqrt(30 / 29))


def test_spacing_uses_the_normalised_objectives() -> None:
    front = np.array([[0.0, 10.0], [1.0, 9.0], [5.0, 5.0], [10.0, 0.0]])
    normalised = Spacing(np.zeros(2), np.full(2, 10.0))(population(front), front)
    assert normalised == pytest.approx(Spacing(*UNIT)(population(front / 10), front / 10))


def test_spread_is_zero_for_an_even_front_reaching_the_extremes() -> None:
    reference = linear_front(1000)
    spread = GeneralizedSpread(reference, *UNIT)
    even = linear_front(11)
    assert spread(population(even), even) == pytest.approx(0.0, abs=1e-12)


def test_spread_penalises_missing_extremes_and_clustering() -> None:
    spread = GeneralizedSpread(linear_front(1000), *UNIT)
    even = linear_front(11)
    half = even[:6]
    uneven = even[[0, 1, 2, 6, 10]]  # nearest-neighbour gaps 1, 1, 1, 4, 4
    for F in (half, uneven):
        value = spread(population(F), F)
        assert value is not None
        assert value > 0.3


def test_spread_does_not_see_gaps_between_evenly_spaced_pairs() -> None:
    # only nearest-neighbour distances enter the generalised spread, so two pairs at
    # the ends of the front look perfectly even (a gap H_0 does see)
    even = linear_front(11)
    pairs = np.vstack((even[:2], even[-2:]))
    spread = GeneralizedSpread(linear_front(1000), *UNIT)
    assert spread(population(pairs), pairs) == pytest.approx(0.0, abs=1e-12)


def test_mean_distance_matches_pdist_with_blocks() -> None:
    F = np.random.default_rng(1).uniform(size=(37, 2))
    metric = MeanPairwiseDistance(*UNIT, block=8)
    assert metric(population(F), F) == pytest.approx(pdist(F).mean())


def test_decision_inertia_ranges_from_zero_to_a_quarter() -> None:
    lower, upper = np.array([0.0, -5.0]), np.array([1.0, 5.0])
    metric = DecisionInertia(lower, upper)
    F = np.zeros((4, 2))
    same = np.tile([0.5, 2.0], (4, 1))
    corners = np.array([[0.0, -5.0], [1.0, 5.0], [0.0, 5.0], [1.0, -5.0]])
    assert metric(population(F, same), F) == pytest.approx(0.0)
    assert metric(population(F, corners), F) == pytest.approx(0.25)


def test_metrics_of_a_single_point_are_undefined() -> None:
    point = np.array([[0.5, 0.5]])
    assert Spacing(*UNIT)(population(point), point) is None
    assert GeneralizedSpread(linear_front(10), *UNIT)(population(point), point) is None
    assert MeanPairwiseDistance(*UNIT)(population(point), point) is None
