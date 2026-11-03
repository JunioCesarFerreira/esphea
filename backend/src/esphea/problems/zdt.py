"""ZDT benchmark problems (Zitzler, Deb and Thiele, 2000).

Every ZDT problem is bi-objective and shares one structure:

    f_1 = x_1,    f_2 = g(x_2..x_n) * h(f_1, g),

with the Pareto front reached when ``g = 1``. The problems differ in ``g``
(how hard the front is to reach) and ``h`` (the shape of the front).
"""

from abc import abstractmethod
from functools import cached_property

import numpy as np

from esphea.core.problem import Problem
from esphea.core.types import FloatArray, frozen

FRONT_RESOLUTION = 100_001
"""Samples of ``f_1`` from which the Pareto front is extracted (resolution 1e-5)."""


class ZDT(Problem):
    """Common structure of the ZDT problems; subclasses define ``g`` and ``h``."""

    def __init__(self, n_var: int, lower: FloatArray | float, upper: FloatArray | float) -> None:
        if n_var < 2:
            raise ValueError(f"ZDT problems need at least 2 variables, got {n_var}")
        super().__init__(n_var=n_var, n_obj=2, lower=lower, upper=upper)

    @abstractmethod
    def _g(self, tail: FloatArray) -> FloatArray:
        """Distance function of the variables ``x_2..x_n``; equals 1 on the Pareto set."""

    @abstractmethod
    def _h(self, f1: FloatArray, g: FloatArray) -> FloatArray:
        """Shape function; ``h(f_1, 1)`` traces the Pareto front."""

    def _evaluate(self, X: FloatArray) -> FloatArray:
        f1 = X[:, 0]
        g = self._g(X[:, 1:])
        return np.column_stack((f1, g * self._h(f1, g)))

    @cached_property
    def _front(self) -> FloatArray:
        """Dense Pareto front: the non-dominated part of the curve ``g = 1``."""
        f1 = np.linspace(0.0, 1.0, FRONT_RESOLUTION)
        f2 = self._h(f1, np.ones_like(f1))
        # f1 increases, so a point is non-dominated iff its f2 is below every earlier f2
        earlier = np.minimum.accumulate(np.concatenate(([np.inf], f2[:-1])))
        keep = f2 < earlier
        return frozen(np.column_stack((f1[keep], f2[keep])))

    def pareto_front(self, n_points: int) -> FloatArray:
        front = self._front
        index = np.unique(np.linspace(0, len(front) - 1, max(n_points, 2)).round().astype(np.intp))
        return front[index].copy()

    @property
    def ideal_point(self) -> FloatArray:
        return frozen(self._front.min(axis=0))

    @property
    def nadir_point(self) -> FloatArray:
        return frozen(self._front.max(axis=0))


def _linear_g(tail: FloatArray) -> FloatArray:
    return 1.0 + 9.0 * tail.mean(axis=1)


def _convex_h(f1: FloatArray, g: FloatArray) -> FloatArray:
    return 1.0 - np.sqrt(f1 / g)


class ZDT1(ZDT):
    """Convex, connected front ``f_2 = 1 - sqrt(f_1)``."""

    def __init__(self, n_var: int = 30) -> None:
        super().__init__(n_var, lower=0.0, upper=1.0)

    @property
    def name(self) -> str:
        return "ZDT1"

    def _g(self, tail: FloatArray) -> FloatArray:
        return _linear_g(tail)

    def _h(self, f1: FloatArray, g: FloatArray) -> FloatArray:
        return _convex_h(f1, g)


class ZDT3(ZDT):
    """Disconnected front: five pieces of ``f_2 = 1 - sqrt(f_1) - f_1 sin(10 pi f_1)``."""

    def __init__(self, n_var: int = 30) -> None:
        super().__init__(n_var, lower=0.0, upper=1.0)

    @property
    def name(self) -> str:
        return "ZDT3"

    def _g(self, tail: FloatArray) -> FloatArray:
        return _linear_g(tail)

    def _h(self, f1: FloatArray, g: FloatArray) -> FloatArray:
        ratio = f1 / g
        return 1.0 - np.sqrt(ratio) - ratio * np.sin(10.0 * np.pi * f1)


class ZDT4(ZDT):
    """Front of ZDT1 behind a Rastrigin-like ``g``: ``21^(n-1)`` local fronts."""

    def __init__(self, n_var: int = 10) -> None:
        # x_1 in [0, 1]; x_2..x_n in [-5, 5]
        lower = np.r_[0.0, np.full(max(n_var - 1, 0), -5.0)]
        upper = np.r_[1.0, np.full(max(n_var - 1, 0), 5.0)]
        super().__init__(n_var, lower=lower, upper=upper)

    @property
    def name(self) -> str:
        return "ZDT4"

    def _g(self, tail: FloatArray) -> FloatArray:
        n: int = tail.shape[1]
        rastrigin: FloatArray = np.sum(tail**2 - 10.0 * np.cos(4.0 * np.pi * tail), axis=1)
        return 1.0 + 10.0 * n + rastrigin

    def _h(self, f1: FloatArray, g: FloatArray) -> FloatArray:
        return _convex_h(f1, g)
