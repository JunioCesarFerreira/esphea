import numpy as np
import pytest
from pymoo.problems import get_problem
from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting

from esphea.problems import DTLZ7


@pytest.mark.parametrize(("n_obj", "k"), [(2, 5), (3, 20), (5, 10)])
def test_matches_pymoo_reference_implementation(
    n_obj: int, k: int, rng: np.random.Generator
) -> None:
    problem = DTLZ7(n_obj=n_obj, k=k)
    reference = get_problem("dtlz7", n_var=problem.n_var, n_obj=n_obj)
    X = rng.random((64, problem.n_var))
    np.testing.assert_allclose(problem.evaluate(X), reference.evaluate(X), rtol=1e-12)


def test_dimensions() -> None:
    problem = DTLZ7()
    assert (problem.n_var, problem.n_obj) == (22, 3)


def test_front_is_attained_with_zero_distance_variables(rng: np.random.Generator) -> None:
    problem = DTLZ7()
    front = problem.pareto_front(500)
    X = np.zeros((len(front), problem.n_var))
    X[:, :2] = front[:, :2]
    np.testing.assert_allclose(problem.evaluate(X), front, atol=1e-12)


@pytest.mark.parametrize("n_obj", [2, 3])
def test_front_is_non_dominated_and_has_the_known_pieces(n_obj: int) -> None:
    problem = DTLZ7(n_obj=n_obj)
    front = problem.pareto_front(400)
    assert len(front) >= 400 ** (1 / (n_obj - 1)) ** (n_obj - 1) - 1
    assert len(NonDominatedSorting().do(front, only_non_dominated_front=True)) == len(front)
    # each positional objective lies in [0, 0.2514] or [0.6316, 0.8594]
    head = front[:, :-1]
    assert np.all((head <= 0.2515) | ((head >= 0.6315) & (head <= 0.8595)))
    assert np.any(head > 0.6315)


def test_ideal_and_nadir_bound_the_front() -> None:
    problem = DTLZ7()
    front = problem.pareto_front(2000)
    assert np.all(front >= problem.ideal_point - 1e-9)
    assert np.all(front <= problem.nadir_point + 1e-9)
    np.testing.assert_allclose(front.min(axis=0), problem.ideal_point, atol=1e-3)
    np.testing.assert_allclose(front.max(axis=0), problem.nadir_point, atol=1e-3)


@pytest.mark.parametrize(("n_obj", "k", "message"), [(1, 10, "objectives"), (3, 0, "k")])
def test_invalid_parameters(n_obj: int, k: int, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        DTLZ7(n_obj=n_obj, k=k)
