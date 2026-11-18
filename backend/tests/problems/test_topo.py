import numpy as np
import pytest
from pydantic import ValidationError
from scipy.spatial import KDTree
from tests.problems.homology import persistent_betti

from esphea.experiments.config import ExperimentConfig, NSGA2Config, TOPOConfig
from esphea.experiments.registry import default_problem_registry
from esphea.problems import TOPO
from esphea.problems.topo import (
    COUNT_RANGES,
    PLANAR_SHAPES,
    SPATIAL_SHAPES,
    ShapeName,
    hyperplane_basis,
    make_shape,
)

CASES: list[tuple[ShapeName, int | None]] = [
    *((shape, None) for shape in PLANAR_SHAPES + SPATIAL_SHAPES if shape not in COUNT_RANGES),
    *(("holes", count) for count in range(1, 7)),
    *(("islands", count) for count in range(2, 9)),
]


def spacing(points: np.ndarray) -> float:
    """Largest distance from a sample point to its nearest neighbour."""
    distances, _ = KDTree(points).query(points, k=2)
    return float(distances[:, 1].max())


def ids(case: tuple[ShapeName, int | None]) -> str:
    shape, count = case
    return f"{shape}{count or ''}"


@pytest.mark.parametrize("n_obj", [2, 3, 4, 6])
def test_basis_is_orthonormal_within_the_hyperplane(n_obj: int) -> None:
    basis = hyperplane_basis(n_obj)
    np.testing.assert_allclose(basis.T @ basis, np.eye(n_obj - 1), atol=1e-12)
    np.testing.assert_allclose(basis.sum(axis=0), 0.0, atol=1e-12)


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_front_is_an_isometric_copy_of_the_shape(case: tuple[ShapeName, int | None]) -> None:
    problem = TOPO(*case)
    assert problem.n_obj == (3 if case[0] in PLANAR_SHAPES else 4)
    assert problem.n_var == problem.n_obj - 1 + 10
    front = problem.pareto_front(1000)
    assert len(front) >= 1000
    np.testing.assert_allclose(front.sum(axis=1), problem.n_obj / 2, atol=1e-12)
    y = (front - 0.5) @ problem.basis
    np.testing.assert_allclose(problem.embed(y), front, atol=1e-12)
    assert problem.shape.distance(y).max() < 1e-12
    # the front lies inside the box of positions, with positive objectives
    assert np.abs(y).max() < 0.5
    assert front.min() > 0.1


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_front_has_the_shapes_betti_numbers(case: tuple[ShapeName, int | None]) -> None:
    problem = TOPO(*case)
    y = (problem.pareto_front(1500) - 0.5) @ problem.basis
    step = spacing(y)
    betti = persistent_betti(y, born_by=1.5 * step, alive_at=3 * step)
    assert betti == problem.shape.betti


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_every_other_point_is_dominated_by_the_front(
    case: tuple[ShapeName, int | None], rng: np.random.Generator
) -> None:
    problem = TOPO(*case)
    F = problem.evaluate(rng.random((3000, problem.n_var)))
    front = problem.pareto_front(20_000)
    for block in np.array_split(F, 10):
        weakly = (front[None, :, :] <= block[:, None, :] + 1e-9).all(axis=2)
        assert np.all(weakly.any(axis=1))


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_off_the_shape_the_lift_is_the_distance_to_it(
    case: tuple[ShapeName, int | None], rng: np.random.Generator
) -> None:
    """With g = 0, f - embed(y) is the distance to the shape, in every objective."""
    problem = TOPO(*case)
    m = problem.n_obj
    X = np.full((2000, problem.n_var), 0.5)
    X[:, : m - 1] = rng.random((2000, m - 1))
    y = X[:, : m - 1] - 0.5
    lift = problem.evaluate(X) - problem.embed(y)
    np.testing.assert_allclose(lift, lift[:, :1].repeat(m, axis=1), atol=1e-12)
    dense = (problem.pareto_front(20_000) - 0.5) @ problem.basis
    nearest, _ = KDTree(dense).query(y)
    # a lattice clipped to the shape stays within two spacings of its border
    assert np.all(lift[:, 0] <= nearest + 1e-12)
    assert np.all(lift[:, 0] >= nearest - 2 * spacing(dense))


@pytest.mark.parametrize("case", CASES, ids=ids)
def test_ideal_and_nadir_are_exact_bounds(case: tuple[ShapeName, int | None]) -> None:
    problem = TOPO(*case)
    front = problem.pareto_front(5000)
    assert np.all(front >= problem.ideal_point - 1e-12)
    assert np.all(front <= problem.nadir_point + 1e-12)
    step = spacing(front)
    np.testing.assert_allclose(front.min(axis=0), problem.ideal_point, atol=step)
    np.testing.assert_allclose(front.max(axis=0), problem.nadir_point, atol=step)


def test_names() -> None:
    assert TOPO("holes", 3).name == "TOPO-holes3"
    assert TOPO("torus", None).name == "TOPO-torus"


@pytest.mark.parametrize(
    ("shape", "count", "message"),
    [
        ("holes", None, "needs a count"),
        ("ring", 2, "takes no count"),
        ("holes", 7, "from 1 to 6"),
        ("islands", 1, "from 2 to 8"),
    ],
)
def test_invalid_counts(shape: ShapeName, count: int | None, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        make_shape(shape, count)


def test_config_builds_the_problem() -> None:
    config = ExperimentConfig(
        name="x", problem=TOPOConfig(shape="torus", count=None, n_obj=4), algorithm=NSGA2Config()
    )
    assert (config.problem.n_obj, config.problem.n_var) == (4, 13)
    problem = default_problem_registry().build(config.problem)
    assert isinstance(problem, TOPO)
    assert problem.name == "TOPO-torus"
    assert ExperimentConfig.model_validate(config.model_dump(mode="json")) == config


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"shape": "sphere", "count": None}, "needs 4 objectives"),
        ({"shape": "ring", "count": 2}, "takes no count"),
        ({"shape": "islands", "count": 1}, "from 2 to 8"),
        ({"shape": "holes", "count": None}, "from 1 to 6"),
    ],
)
def test_config_rejects_inconsistent_shapes(fields: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        TOPOConfig.model_validate(fields)
