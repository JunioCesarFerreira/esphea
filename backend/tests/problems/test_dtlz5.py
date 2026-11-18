import numpy as np
import pytest
from pymoo.problems import get_problem

from esphea.problems import DTLZ5


def test_matches_pymoo_reference_implementation(rng: np.random.Generator) -> None:
    problem = DTLZ5()
    reference = get_problem("dtlz5", n_var=problem.n_var, n_obj=3)
    X = rng.random((64, problem.n_var))
    np.testing.assert_allclose(problem.evaluate(X), reference.evaluate(X), rtol=1e-12)
    assert (problem.n_var, problem.n_obj, problem.name) == (12, 3, "DTLZ5")


def test_front_is_an_arc_reached_with_centred_distance_variables(
    rng: np.random.Generator,
) -> None:
    problem = DTLZ5()
    X = np.full((500, problem.n_var), 0.5)
    X[:, :2] = rng.random((500, 2))
    F = problem.evaluate(X)
    np.testing.assert_allclose(F[:, 0], F[:, 1], atol=1e-12)  # f_1 = f_2: a curve
    np.testing.assert_allclose(np.linalg.norm(F, axis=1), 1.0, atol=1e-12)
    front = problem.pareto_front(200)
    np.testing.assert_allclose(front[:, 0], front[:, 1])
    np.testing.assert_allclose(np.linalg.norm(front, axis=1), 1.0)
    # along the arc f_1 = f_2 fall while f_3 grows: mutually non-dominated, one piece
    assert np.all(np.diff(front[:, 0]) < 0)
    assert np.all(np.diff(front[:, 2]) > 0)
    np.testing.assert_allclose(front.min(axis=0), problem.ideal_point, atol=1e-12)
    np.testing.assert_allclose(front.max(axis=0), problem.nadir_point, atol=1e-12)


def test_every_point_is_dominated_by_the_arc(rng: np.random.Generator) -> None:
    """The point of the arc with sin(t) = min(1, f_3) is weakly below every objective vector."""
    problem = DTLZ5()
    F = problem.evaluate(rng.random((20_000, problem.n_var)))
    sin_t = np.minimum(1.0, F[:, 2])
    cos_t = np.sqrt(1.0 - sin_t**2)
    arc = np.column_stack((cos_t / np.sqrt(2), cos_t / np.sqrt(2), sin_t))
    assert np.all(arc <= F + 1e-12)


def test_invalid_k() -> None:
    with pytest.raises(ValueError, match="k"):
        DTLZ5(k=0)
