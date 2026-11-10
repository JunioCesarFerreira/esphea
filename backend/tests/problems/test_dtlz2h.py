import numpy as np
import pytest
from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting

from esphea.experiments.config import DTLZ2HConfig, ExperimentConfig, NSGA3Config
from esphea.experiments.registry import default_problem_registry
from esphea.problems import DTLZ2, DTLZ2H


def test_dimensions_and_bounds() -> None:
    problem = DTLZ2H()
    assert (problem.n_var, problem.n_obj, problem.name) == (12, 3, "DTLZ2-H")
    np.testing.assert_array_equal(problem.ideal_point, np.zeros(3))
    np.testing.assert_array_equal(problem.nadir_point, np.ones(3))


def test_equals_dtlz2_outside_the_cap(rng: np.random.Generator) -> None:
    problem, plain = DTLZ2H(), DTLZ2(n_obj=3, k=10)
    X = rng.random((2000, problem.n_var))
    F, G = problem.evaluate(X), plain.evaluate(X)
    outside = problem.angle_to_centre(G) >= problem.radius
    assert 0 < outside.sum() < len(X)
    np.testing.assert_allclose(F[outside], G[outside], rtol=1e-12)
    assert np.all(F[~outside] > G[~outside])


@pytest.mark.parametrize("radius", [5.0, 20.0, 25.0])
def test_every_point_over_the_cap_is_dominated_by_its_meridian(
    radius: float, rng: np.random.Generator
) -> None:
    problem = DTLZ2H(radius=radius)
    s = np.abs(rng.normal(size=(200_000, 3)))
    s /= np.linalg.norm(s, axis=1, keepdims=True)
    alpha = problem.angle_to_centre(s)
    cap = (alpha < problem.radius) & (alpha > 1e-9)
    s, alpha = s[cap], alpha[cap]
    centre = np.full(3, 1 / np.sqrt(3))
    meridian = (s - np.outer(np.cos(alpha), centre)) / np.sin(alpha)[:, None]
    boundary = np.cos(problem.radius) * centre + np.sin(problem.radius) * meridian
    over = s * (1 + np.clip(1 - alpha / problem.radius, 0, None))[:, None]
    assert np.all(boundary <= over)
    assert np.all(np.linalg.norm(over, axis=1) > 1)


def test_front_is_the_octant_without_the_cap() -> None:
    problem = DTLZ2H()
    front = problem.pareto_front(1000)
    assert len(front) >= 1000
    np.testing.assert_allclose(np.linalg.norm(front, axis=1), 1.0)
    assert np.all(problem.angle_to_centre(front) >= problem.radius)
    assert len(NonDominatedSorting().do(front, only_non_dominated_front=True)) == len(front)
    # the hole: no front point near the centre, but points all around it
    assert problem.angle_to_centre(front).min() < problem.radius + np.radians(3)


def test_front_is_attained_with_centred_distance_variables(rng: np.random.Generator) -> None:
    problem = DTLZ2H()
    X = np.full((500, problem.n_var), 0.5)
    X[:, :2] = rng.random((500, 2))
    F = problem.evaluate(X)
    outside = problem.angle_to_centre(F) >= problem.radius
    np.testing.assert_allclose(np.linalg.norm(F[outside], axis=1), 1.0)


def test_invalid_radius() -> None:
    with pytest.raises(ValueError, match="radius"):
        DTLZ2H(radius=40.0)


def test_config_builds_the_problem() -> None:
    config = ExperimentConfig(name="x", problem=DTLZ2HConfig(radius=15.0), algorithm=NSGA3Config())
    assert (config.problem.n_obj, config.problem.n_var, config.pop_size) == (3, 12, 92)
    problem = default_problem_registry().build(config.problem)
    assert isinstance(problem, DTLZ2H)
    assert problem.radius == pytest.approx(np.radians(15.0))
    assert ExperimentConfig.model_validate(config.model_dump(mode="json")) == config
