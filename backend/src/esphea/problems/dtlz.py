"""DTLZ benchmark problems (Deb, Thiele, Laumanns and Zitzler, 2005)."""

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
