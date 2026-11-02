import numpy as np
import pytest

from esphea.metrics import IGD, Hypervolume, IGDPlus, non_dominated_mask
from esphea.problems import DTLZ2


def test_reference_front_scores_zero_igd(dtlz2: DTLZ2) -> None:
    front = dtlz2.pareto_front(300)
    assert IGD(front)(front) == pytest.approx(0.0)
    assert IGDPlus(front)(front) == pytest.approx(0.0)


def test_igd_grows_when_front_is_shifted(dtlz2: DTLZ2) -> None:
    front = dtlz2.pareto_front(300)
    assert IGD(front)(front * 1.2) > IGD(front)(front * 1.05) > 0.0


def test_hypervolume_of_single_point() -> None:
    hv = Hypervolume(np.array([2.0, 2.0]))
    assert hv(np.array([[1.0, 1.0]])) == pytest.approx(1.0)


def test_hypervolume_ignores_points_beyond_reference() -> None:
    hv = Hypervolume(np.array([1.0, 1.0]))
    assert hv(np.array([[2.0, 0.5]])) == 0.0


def test_hypervolume_switches_to_approximation_in_many_objectives() -> None:
    problem = DTLZ2(n_obj=8, k=5)
    hv = Hypervolume(np.full(8, 1.1))
    assert not hv.exact
    assert hv(problem.pareto_front(100)) > 0.0


def test_non_dominated_mask() -> None:
    F = np.array([[1.0, 2.0], [2.0, 1.0], [2.0, 2.0]])
    np.testing.assert_array_equal(non_dominated_mask(F), [True, True, False])
