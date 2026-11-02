from collections.abc import Callable

import numpy as np
import pytest

from esphea.operators import PolynomialMutation, SimulatedBinaryCrossover
from esphea.problems import DTLZ2


def test_sbx_lineage_and_bounds(dtlz2: DTLZ2, rng: np.random.Generator) -> None:
    X = rng.random((20, dtlz2.n_var))
    matings = rng.integers(0, 20, size=(10, 2)).astype(np.intp)
    offspring = SimulatedBinaryCrossover(eta=15, prob=1.0).cross(dtlz2, X, matings, rng)
    assert offspring.X.shape == (20, dtlz2.n_var)
    assert offspring.parents.shape == (20, 2)
    np.testing.assert_array_equal(offspring.parents[:10], matings)
    np.testing.assert_array_equal(offspring.parents[10:], matings)
    assert np.all((offspring.X >= 0.0) & (offspring.X <= 1.0))


def test_sbx_without_crossover_copies_parents(dtlz2: DTLZ2, rng: np.random.Generator) -> None:
    X = rng.random((8, dtlz2.n_var))
    matings = np.array([[0, 1], [2, 3], [4, 5]], dtype=np.intp)
    offspring = SimulatedBinaryCrossover(prob=0.0).cross(dtlz2, X, matings, rng)
    np.testing.assert_array_equal(offspring.X[:3], X[matings[:, 0]])
    np.testing.assert_array_equal(offspring.X[3:], X[matings[:, 1]])


def test_sbx_children_stay_close_to_parents_for_large_eta(
    dtlz2: DTLZ2, rng: np.random.Generator
) -> None:
    """Each child variable lies near the value of one of the two parents."""
    X = rng.random((2, dtlz2.n_var))
    matings = np.zeros((500, 2), dtype=np.intp)
    matings[:, 1] = 1
    offspring = SimulatedBinaryCrossover(eta=200.0, prob=1.0, prob_var=1.0).cross(
        dtlz2, X, matings, rng
    )
    gap = np.minimum(np.abs(offspring.X - X[0]), np.abs(offspring.X - X[1]))
    assert np.median(gap) < 0.01


def test_mutation_does_not_modify_input_and_respects_bounds(
    dtlz2: DTLZ2, rng: np.random.Generator
) -> None:
    X = rng.random((50, dtlz2.n_var))
    original = X.copy()
    Y = PolynomialMutation(eta=20, prob_var=0.5).mutate(dtlz2, X, rng)
    np.testing.assert_array_equal(X, original)
    assert np.all((Y >= 0.0) & (Y <= 1.0))
    assert np.any(Y != X)


def test_mutation_default_rate_is_one_over_n(dtlz2: DTLZ2, rng: np.random.Generator) -> None:
    X = rng.random((4000, dtlz2.n_var))
    Y = PolynomialMutation().mutate(dtlz2, X, rng)
    rate = np.mean(Y != X)
    assert rate == pytest.approx(1 / dtlz2.n_var, rel=0.1)


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (lambda: SimulatedBinaryCrossover(eta=0), "eta"),
        (lambda: SimulatedBinaryCrossover(prob=1.5), "prob"),
        (lambda: PolynomialMutation(eta=-1), "eta"),
        (lambda: PolynomialMutation(prob_var=2.0), "prob_var"),
    ],
)
def test_invalid_parameters(factory: Callable[[], object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        factory()
