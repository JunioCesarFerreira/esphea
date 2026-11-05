"""DTLZ benchmark problems (Deb, Thiele, Laumanns and Zitzler, 2005)."""

from functools import cached_property

import numpy as np

from esphea.core.problem import Problem
from esphea.core.types import FloatArray, frozen
from esphea.reference_directions import das_dennis, das_dennis_partitions_for


class DTLZ2(Problem):
    """Scalable DTLZ2 problem.

    ``n_var = n_obj + k - 1``; the first ``n_obj - 1`` variables are positional
    and the last ``k`` are distance variables. The Pareto front is the portion
    of the unit hypersphere in the positive orthant, reached when every
    distance variable equals 0.5.
    """

    def __init__(self, n_obj: int = 3, k: int = 10) -> None:
        if n_obj < 2:
            raise ValueError(f"DTLZ2 needs at least 2 objectives, got {n_obj}")
        if k < 1:
            raise ValueError(f"k must be positive, got {k}")
        super().__init__(n_var=n_obj + k - 1, n_obj=n_obj, lower=0.0, upper=1.0)
        self.k = k
        # Column of the angular factors that ends each objective's product:
        # f_i uses cos(theta_0..theta_{M-2-i}) and, for i > 0, sin(theta_{M-1-i}).
        self._angle_index = n_obj - 1 - np.arange(n_obj)

    @property
    def name(self) -> str:
        return "DTLZ2"

    def _evaluate(self, X: FloatArray) -> FloatArray:
        m = self.n_obj
        g = np.sum((X[:, m - 1 :] - 0.5) ** 2, axis=1)
        theta = X[:, : m - 1] * (np.pi / 2.0)
        # cos_prefix[:, j] = prod_{l < j} cos(theta_l), with cos_prefix[:, 0] = 1
        cos_prefix = np.ones((X.shape[0], m))
        np.cumprod(np.cos(theta), axis=1, out=cos_prefix[:, 1:])
        F = cos_prefix[:, self._angle_index]
        F[:, 1:] *= np.sin(theta[:, self._angle_index[1:]])
        F *= (1.0 + g)[:, None]
        return F

    def pareto_front(self, n_points: int) -> FloatArray:
        partitions = das_dennis_partitions_for(self.n_obj, n_points)
        directions = das_dennis(self.n_obj, partitions)
        return directions / np.linalg.norm(directions, axis=1, keepdims=True)

    @property
    def ideal_point(self) -> FloatArray:
        return frozen(np.zeros(self.n_obj))

    @property
    def nadir_point(self) -> FloatArray:
        return frozen(np.ones(self.n_obj))


DTLZ7_RESOLUTION = 100_001
"""Samples of ``f_i`` in [0, 1] from which the Pareto-optimal intervals are extracted."""


class DTLZ7(Problem):
    """Scalable DTLZ7 problem with a disconnected front.

    ``n_var = n_obj + k - 1``; ``f_i = x_i`` for ``i < M`` and

        f_M = (1 + g) * (M - sum_i f_i / (1 + g) * (1 + sin(3 pi f_i))),
        g = 1 + 9 / k * sum(x_M..x_n),

    so the front (``g = 1``) is ``f_M = 2M - sum_i phi(f_i)`` with
    ``phi(f) = f (1 + sin(3 pi f))``. Because ``f_M`` is separable, a point is
    Pareto optimal iff every ``f_i`` is Pareto optimal for ``M = 2``: the front
    is the product of two intervals per coordinate, i.e. ``2^(M-1)`` pieces.
    """

    def __init__(self, n_obj: int = 3, k: int = 20) -> None:
        if n_obj < 2:
            raise ValueError(f"DTLZ7 needs at least 2 objectives, got {n_obj}")
        if k < 1:
            raise ValueError(f"k must be positive, got {k}")
        super().__init__(n_var=n_obj + k - 1, n_obj=n_obj, lower=0.0, upper=1.0)
        self.k = k

    @property
    def name(self) -> str:
        return "DTLZ7"

    def _evaluate(self, X: FloatArray) -> FloatArray:
        m = self.n_obj
        f = X[:, : m - 1]
        g = 1.0 + 9.0 / self.k * np.sum(X[:, m - 1 :], axis=1)
        h = m - np.sum(f / (1.0 + g)[:, None] * (1.0 + np.sin(3.0 * np.pi * f)), axis=1)
        return np.column_stack((f, (1.0 + g) * h))

    @staticmethod
    def _phi(f: FloatArray) -> FloatArray:
        return f * (1.0 + np.sin(3.0 * np.pi * f))

    @cached_property
    def _optimal_coordinates(self) -> FloatArray:
        """Values of one ``f_i`` on the front: ``phi`` exceeds its value at every smaller ``f``."""
        f = np.linspace(0.0, 1.0, DTLZ7_RESOLUTION)
        phi = self._phi(f)
        earlier = np.maximum.accumulate(np.concatenate(([-np.inf], phi[:-1])))
        return frozen(f[phi > earlier])

    def pareto_front(self, n_points: int) -> FloatArray:
        values = self._optimal_coordinates
        per_axis = max(2, int(np.ceil(max(n_points, 2) ** (1.0 / (self.n_obj - 1)))))
        index = np.unique(np.linspace(0, len(values) - 1, per_axis).round().astype(np.intp))
        grid = np.meshgrid(*[values[index]] * (self.n_obj - 1), indexing="ij")
        f = np.column_stack([axis.ravel() for axis in grid])
        last = 2.0 * self.n_obj - np.sum(self._phi(f), axis=1)
        return np.column_stack((f, last))

    @property
    def ideal_point(self) -> FloatArray:
        best = float(self._phi(self._optimal_coordinates).max())
        return frozen(np.r_[np.zeros(self.n_obj - 1), 2.0 * self.n_obj - (self.n_obj - 1) * best])

    @property
    def nadir_point(self) -> FloatArray:
        far = float(self._optimal_coordinates.max())
        return frozen(np.r_[np.full(self.n_obj - 1, far), 2.0 * self.n_obj])
