from collections.abc import Callable

import numpy as np
import pytest
from pymoo.problems import get_problem

from esphea.problems import ZDT1, ZDT3, ZDT4
from esphea.problems.zdt import ZDT

PROBLEMS: dict[str, Callable[..., ZDT]] = {"zdt1": ZDT1, "zdt3": ZDT3, "zdt4": ZDT4}


def _random_decisions(problem: ZDT, rng: np.random.Generator, n: int) -> np.ndarray:
    return problem.lower + rng.random((n, problem.n_var)) * (problem.upper - problem.lower)


@pytest.mark.parametrize("name", PROBLEMS)
@pytest.mark.parametrize("n_var", [2, 10, 30])
def test_matches_pymoo_reference_implementation(
    name: str, n_var: int, rng: np.random.Generator
) -> None:
    problem = PROBLEMS[name](n_var=n_var)
    reference = get_problem(name, n_var=n_var)
    np.testing.assert_array_equal(problem.lower, reference.xl)
    np.testing.assert_array_equal(problem.upper, reference.xu)
    X = _random_decisions(problem, rng, 64)
    np.testing.assert_allclose(problem.evaluate(X), reference.evaluate(X), rtol=1e-12)


@pytest.mark.parametrize(("name", "n_var"), [("zdt1", 30), ("zdt3", 30), ("zdt4", 10)])
def test_defaults(name: str, n_var: int) -> None:
    problem = PROBLEMS[name]()
    assert (problem.n_var, problem.n_obj, problem.name) == (n_var, 2, name.upper())


@pytest.mark.parametrize("name", PROBLEMS)
def test_front_is_attained_by_the_pareto_set(name: str) -> None:
    """Front points are images of decisions with x_2..x_n at their optimum (g = 1)."""
    problem = PROBLEMS[name]()
    front = problem.pareto_front(300)
    X = np.zeros((len(front), problem.n_var))
    X[:, 0] = front[:, 0]
    np.testing.assert_allclose(problem.evaluate(X), front, rtol=0, atol=1e-12)


@pytest.mark.parametrize("name", PROBLEMS)
def test_front_matches_pymoo(name: str) -> None:
    problem = PROBLEMS[name]()
    front = problem.pareto_front(500)
    reference = get_problem(name).pareto_front(500)
    # mutual distance of the two samples (both are dense samples of the same front)
    gaps = np.linalg.norm(front[:, None, :] - reference[None, :, :], axis=2)
    assert gaps.min(axis=1).max() < 0.02
    assert gaps.min(axis=0).max() < 0.02


def test_front_is_non_dominated_and_sized() -> None:
    front = ZDT3().pareto_front(1000)
    assert 990 <= len(front) <= 1000
    order = np.argsort(front[:, 0])
    assert np.all(np.diff(front[order, 1]) < 0)  # bi-objective: f2 strictly decreases with f1


def test_zdt3_front_has_five_pieces() -> None:
    front = ZDT3().pareto_front(2000)
    steps = np.diff(front[:, 0])
    assert np.count_nonzero(steps > 0.05) == 4


@pytest.mark.parametrize(
    ("name", "ideal", "nadir"),
    [
        ("zdt1", (0.0, 0.0), (1.0, 1.0)),
        ("zdt3", (0.0, -0.773369), (0.851833, 1.0)),
        ("zdt4", (0.0, 0.0), (1.0, 1.0)),
    ],
)
def test_ideal_and_nadir(name: str, ideal: tuple[float, float], nadir: tuple[float, float]) -> None:
    problem = PROBLEMS[name]()
    np.testing.assert_allclose(problem.ideal_point, ideal, atol=1e-5)
    np.testing.assert_allclose(problem.nadir_point, nadir, atol=1e-5)


def test_rejects_a_single_variable() -> None:
    with pytest.raises(ValueError, match="at least 2 variables"):
        ZDT1(n_var=1)
