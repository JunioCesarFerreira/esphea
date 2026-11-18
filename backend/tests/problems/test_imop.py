from collections.abc import Callable

import numpy as np
import pytest
from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting
from tests.problems.homology import persistent_betti

from esphea.problems import IMOP4, IMOP5, IMOP6, IMOP7, IMOP8
from esphea.problems.imop import IMOP

PROBLEMS: dict[str, Callable[..., IMOP]] = {
    "imop4": IMOP4,
    "imop5": IMOP5,
    "imop6": IMOP6,
    "imop7": IMOP7,
    "imop8": IMOP8,
}


def published(name: str, x: np.ndarray) -> np.ndarray:
    """One decision vector, literally as defined by Tian et al. (2019) / PlatEMO."""
    y1 = np.mean(x[0:5:2]) ** 0.05
    y2 = np.mean(x[1:5:2]) ** 10
    g = np.sum((x[5:] - 0.5) ** 2)
    if name == "imop4":
        y = np.mean(x[:5]) ** 0.05
        return np.asarray((1 + g) * np.array([y, y + np.sin(10 * np.pi * y) / 10, 1 - y]))
    if name == "imop5":
        f1 = 0.4 * np.cos(np.pi * np.ceil(y1 * 8) / 4) + 0.1 * y2 * np.cos(16 * np.pi * y1)
        f2 = 0.4 * np.sin(np.pi * np.ceil(y1 * 8) / 4) + 0.1 * y2 * np.sin(16 * np.pi * y1)
        return np.asarray(np.array([f1, f2, 0.5 - f1 - f2]) + g)
    if name == "imop6":
        r = max(0.0, min(np.sin(3 * np.pi * y1) ** 2, np.sin(3 * np.pi * y2) ** 2) - 0.05)
        lifted = np.array([(1 + g) * y1, (1 + g) * y2, (0.5 + g) * (2 - y1 - y2)]) + np.ceil(r)
        return np.asarray(lifted)
    if name == "imop7":
        f = (1 + g) * np.array(
            [
                np.cos(y1 * np.pi / 2) * np.cos(y2 * np.pi / 2),
                np.cos(y1 * np.pi / 2) * np.sin(y2 * np.pi / 2),
                np.sin(y1 * np.pi / 2),
            ]
        )
        r = min(abs(f[0] - f[1]), abs(f[1] - f[2]), abs(f[2] - f[0]))
        return np.asarray(f + 10 * max(0.0, r - 0.1))
    f12 = np.array([y1, y2])
    f3 = (1 + g) * (3 - np.sum(f12 / (1 + g) * (1 + np.sin(19 * np.pi * f12))))
    return np.array([y1, y2, f3])


def decisions(problem: IMOP, y1: np.ndarray, y2: np.ndarray, distance: float = 0.5) -> np.ndarray:
    """Decision vectors with the given positions (inverting the power maps)."""
    X = np.full((len(y1), problem.n_var), distance)
    if isinstance(problem, IMOP4):
        X[:, :5] = (y1**20)[:, None]
    else:
        X[:, 0:5:2] = (y1**20)[:, None]
        X[:, 1:5:2] = (y2**0.1)[:, None]
    return X


@pytest.mark.parametrize("name", PROBLEMS)
@pytest.mark.parametrize("n_var", [6, 10, 30])
def test_matches_the_published_definition(name: str, n_var: int, rng: np.random.Generator) -> None:
    problem = PROBLEMS[name](n_var=n_var)
    X = rng.random((200, n_var))
    expected = np.array([published(name, x) for x in X])
    np.testing.assert_allclose(problem.evaluate(X), expected, rtol=1e-12, atol=1e-12)
    assert (problem.n_obj, problem.name) == (3, name.upper())


def test_rejects_too_few_variables() -> None:
    with pytest.raises(ValueError, match="more than 5"):
        IMOP5(n_var=5)


def test_positions_are_biased(rng: np.random.Generator) -> None:
    """Uniform decisions crowd y_1 near 1 and y_2 near 0."""
    y1, y2 = IMOP._y(rng.random((10_000, 10)))
    assert np.median(y1) > 0.95
    assert np.median(y2) < 0.01


@pytest.mark.parametrize("name", PROBLEMS)
def test_front_is_non_dominated_and_bounded_by_ideal_and_nadir(name: str) -> None:
    problem = PROBLEMS[name]()
    front = problem.pareto_front(1000)
    assert len(front) >= 1000
    assert len(NonDominatedSorting().do(front, only_non_dominated_front=True)) == len(front)
    assert np.all(front >= problem.ideal_point - 1e-12)
    assert np.all(front <= problem.nadir_point + 1e-12)
    np.testing.assert_allclose(front.min(axis=0), problem.ideal_point, atol=0.02)
    np.testing.assert_allclose(front.max(axis=0), problem.nadir_point, atol=0.02)


@pytest.mark.parametrize("name", PROBLEMS)
def test_no_attainable_point_dominates_the_front(name: str, rng: np.random.Generator) -> None:
    """Positions drawn uniformly (not through the biased maps), distances near the optimum."""
    problem = PROBLEMS[name]()
    X = decisions(problem, rng.random(3000), rng.random(3000))
    X[:, 5:] = rng.uniform(0.4, 0.6, size=(3000, problem.n_var - 5))
    F = problem.evaluate(X)
    front = problem.pareto_front(1500)
    for block in np.array_split(front, 10):
        weakly = (F[None, :, :] <= block[:, None, :]).all(axis=2)
        strictly = (F[None, :, :] < block[:, None, :] - 1e-9).any(axis=2)
        assert not np.any(weakly & strictly)


@pytest.mark.parametrize("name", PROBLEMS)
def test_attainable_points_are_dominated_by_the_front(name: str, rng: np.random.Generator) -> None:
    """Up to the spacing of a dense sample of the front."""
    problem = PROBLEMS[name]()
    X = decisions(problem, rng.random(2000), rng.random(2000))
    X[:, 5:] = rng.uniform(0.3, 0.7, size=(2000, problem.n_var - 5))
    F = problem.evaluate(X)
    front = problem.pareto_front(20_000)
    for block in np.array_split(F, 20):
        covered = (front[None, :, :] <= block[:, None, :] + 0.01).all(axis=2).any(axis=1)
        assert np.all(covered)


def test_imop4_front_is_one_curve() -> None:
    problem = IMOP4()
    front = problem.pareto_front(500)
    assert np.all(np.diff(front[:, 0]) > 0)  # f_1 grows, f_3 falls: mutually non-dominated
    assert np.all(np.diff(front[:, 2]) < 0)
    steps = np.linalg.norm(np.diff(front, axis=0), axis=1)
    np.testing.assert_allclose(steps, steps.mean(), rtol=0.01)  # equally spaced, no gap


def test_imop5_front_is_eight_discs() -> None:
    front = IMOP5().pareto_front(4000)
    np.testing.assert_allclose(front.sum(axis=1), 0.5, atol=1e-12)
    # gaps between neighbouring discs: 0.8 sin(pi / 8) - 0.2 = 0.106, i.e. radius 0.053
    assert persistent_betti(front[:, :2], born_by=0.02, alive_at=0.04) == (8, 0)


def test_imop6_front_is_a_grid_with_nine_holes() -> None:
    front = IMOP6().pareto_front(3000)
    np.testing.assert_allclose(front[:, 2], 1.0 - front[:, :2].sum(axis=1) / 2, atol=1e-12)
    # the front is a graph over (f_1, f_2): its projection has the same topology
    assert persistent_betti(front[:, :2], born_by=0.03, alive_at=0.1) == (1, 9)


def test_imop7_front_is_a_star_of_bands() -> None:
    problem = IMOP7()
    front = problem.pareto_front(3000)
    np.testing.assert_allclose(np.linalg.norm(front, axis=1), 1.0, atol=1e-12)
    assert np.all(problem.spread(front) <= 0.1)
    # the bands meet at the centre of the octant and leave notches open to its edges
    centre = np.full(3, 1 / np.sqrt(3))
    assert np.linalg.norm(front - centre, axis=1).min() < 0.02
    assert persistent_betti(front[:, :2], born_by=0.05, alive_at=0.1) == (1, 0)


def test_imop8_front_has_a_hundred_pieces() -> None:
    values = IMOP8()._optimal_coordinates
    assert np.count_nonzero(np.diff(values) > 1e-3) == 9  # ten intervals per axis
    front = IMOP8().pareto_front(10_000)
    assert persistent_betti(front[:, :2], born_by=0.01, alive_at=0.012) == (100, 0)


def test_at_the_optimal_distance_positions_land_on_the_front_or_are_lifted(
    rng: np.random.Generator,
) -> None:
    """With g = 0 (distance variables at 0.5), checked against each front's description."""
    y1, y2 = rng.random(3000), rng.random(3000)

    imop5 = IMOP5()
    F = imop5.evaluate(decisions(imop5, y1, y2))
    to_centres = np.linalg.norm(F[:, None, :2] - IMOP5.centres()[None, :, :], axis=2)
    assert np.all(to_centres.min(axis=1) <= 0.1 + 1e-12)
    np.testing.assert_allclose(F.sum(axis=1), 0.5, atol=1e-12)

    imop6 = IMOP6()
    F = imop6.evaluate(decisions(imop6, y1, y2))
    plane = np.column_stack((y1, y2, 1 - (y1 + y2) / 2))
    on = IMOP6.on_strips(y1, y2)
    np.testing.assert_allclose(F[on], plane[on], atol=1e-9)
    np.testing.assert_allclose(F[~on], plane[~on] + 1, atol=1e-9)

    imop7 = IMOP7()
    F = imop7.evaluate(decisions(imop7, y1, y2))
    a, b = y1 * np.pi / 2, y2 * np.pi / 2
    sphere = np.column_stack((np.cos(a) * np.cos(b), np.cos(a) * np.sin(b), np.sin(a)))
    banded = IMOP7.spread(sphere) <= 0.1
    np.testing.assert_allclose(F[banded], sphere[banded], atol=1e-9)
    lift = F[~banded] - sphere[~banded]
    np.testing.assert_allclose(lift, lift[:, :1].repeat(3, axis=1), atol=1e-9)
    assert np.all(lift > 0)

    imop8 = IMOP8()
    F = imop8.evaluate(decisions(imop8, y1, y2))
    np.testing.assert_allclose(F[:, :2], np.column_stack((y1, y2)), atol=1e-9)
    np.testing.assert_allclose(F[:, 2], 3 - IMOP8._phi(F[:, 0]) - IMOP8._phi(F[:, 1]), atol=1e-12)
