import numpy as np
import pytest
from pymoo.problems import get_problem

from esphea.problems import DTLZ2


@pytest.mark.parametrize(("n_obj", "k"), [(2, 5), (3, 10), (5, 10), (10, 3)])
def test_matches_pymoo_reference_implementation(
    n_obj: int, k: int, rng: np.random.Generator
) -> None:
    problem = DTLZ2(n_obj=n_obj, k=k)
    reference = get_problem("dtlz2", n_var=problem.n_var, n_obj=n_obj)
    X = rng.random((64, problem.n_var))
    np.testing.assert_allclose(problem.evaluate(X), reference.evaluate(X), rtol=1e-12)


def test_dimensions(dtlz2: DTLZ2) -> None:
    assert (dtlz2.n_var, dtlz2.n_obj) == (12, 3)
    np.testing.assert_array_equal(dtlz2.lower, np.zeros(12))
    np.testing.assert_array_equal(dtlz2.upper, np.ones(12))


def test_optimal_distance_variables_lie_on_unit_sphere(
    dtlz2: DTLZ2, rng: np.random.Generator
) -> None:
    X = rng.random((100, dtlz2.n_var))
    X[:, dtlz2.n_obj - 1 :] = 0.5
    F = dtlz2.evaluate(X)
    np.testing.assert_allclose(np.linalg.norm(F, axis=1), 1.0)


def test_pareto_front_sample(dtlz2: DTLZ2) -> None:
    front = dtlz2.pareto_front(500)
    assert front.shape[0] >= 500
    assert front.shape[1] == 3
    np.testing.assert_allclose(np.linalg.norm(front, axis=1), 1.0)
    assert np.all(front >= 0.0)


def test_rejects_wrong_shape(dtlz2: DTLZ2) -> None:
    with pytest.raises(ValueError, match="shape"):
        dtlz2.evaluate(np.zeros((4, 5)))


@pytest.mark.parametrize(("n_obj", "k", "message"), [(1, 10, "objectives"), (3, 0, "k")])
def test_invalid_parameters(n_obj: int, k: int, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        DTLZ2(n_obj=n_obj, k=k)
