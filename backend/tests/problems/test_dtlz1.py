import numpy as np
import pytest
from pymoo.problems import get_problem

from esphea.problems import DTLZ1


@pytest.mark.parametrize(("n_obj", "k"), [(2, 5), (3, 5), (5, 3)])
def test_matches_pymoo_reference_implementation(
    n_obj: int, k: int, rng: np.random.Generator
) -> None:
    problem = DTLZ1(n_obj=n_obj, k=k)
    reference = get_problem("dtlz1", n_var=problem.n_var, n_obj=n_obj)
    X = rng.random((64, problem.n_var))
    np.testing.assert_allclose(problem.evaluate(X), reference.evaluate(X), rtol=1e-12)


def test_dimensions() -> None:
    problem = DTLZ1()
    assert (problem.n_var, problem.n_obj, problem.name) == (7, 3, "DTLZ1")


@pytest.mark.parametrize("n_obj", [2, 3, 4])
def test_front_is_the_simplex_reached_with_centred_distance_variables(
    n_obj: int, rng: np.random.Generator
) -> None:
    problem = DTLZ1(n_obj=n_obj)
    X = np.full((500, problem.n_var), 0.5)
    X[:, : n_obj - 1] = rng.random((500, n_obj - 1))
    np.testing.assert_allclose(problem.evaluate(X).sum(axis=1), 0.5, atol=1e-12)
    front = problem.pareto_front(300)
    np.testing.assert_allclose(front.sum(axis=1), 0.5, atol=1e-12)
    assert np.all(front >= 0)
    np.testing.assert_allclose(front.min(axis=0), problem.ideal_point)
    np.testing.assert_allclose(front.max(axis=0), problem.nadir_point)


def test_local_fronts_lie_behind_the_global_one() -> None:
    """Distance variables at 0 or 1 sit on local optima of g: a parallel, farther simplex.

    Each of the k = 5 variables adds 100 (0.25 - cos(10 pi)) = -75 to g = 500 + ...: g = 125.
    """
    problem = DTLZ1()
    X = np.full((3, problem.n_var), 0.5)
    X[0, 2:] = 0.0
    X[1, 2:] = 1.0
    sums = problem.evaluate(X).sum(axis=1)
    np.testing.assert_allclose(sums, [0.5 * 126, 0.5 * 126, 0.5])


@pytest.mark.parametrize(("n_obj", "k", "message"), [(1, 5, "objectives"), (3, 0, "k")])
def test_invalid_parameters(n_obj: int, k: int, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        DTLZ1(n_obj=n_obj, k=k)
