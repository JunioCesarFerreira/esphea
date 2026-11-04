"""Classical diversity metrics of a population, for comparison with topological summaries.

Objective-space metrics work on objectives scaled by the problem's ideal and
nadir points (ideal -> 0, nadir -> 1), so that values are comparable across
objectives, generations and experiments; the decision-space metric works on
variables scaled to ``[0, 1]`` by the problem's bounds.
"""

from abc import ABC, abstractmethod

import numpy as np
from scipy.spatial import KDTree
from scipy.spatial.distance import cdist

from esphea.core.population import Population
from esphea.core.types import FloatArray

PAIRWISE_BLOCK = 1024
"""Rows per block of the pairwise distances (bounds memory for large populations)."""


class DiversityMetric(ABC):
    """Maps a population (and the first front of it) to a scalar, or ``None`` if undefined."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier used for storage and display (e.g. ``"spacing"``)."""

    @abstractmethod
    def __call__(self, population: Population, front: FloatArray) -> float | None:
        """Compute the metric; ``front`` holds the objectives of the first front."""


def _scale(values: FloatArray, low: FloatArray, high: FloatArray) -> FloatArray:
    width = np.where(high > low, high - low, 1.0)
    return (values - low) / width


def _nearest_other(points: FloatArray, *, p: float = 2.0) -> FloatArray:
    """Distance from each point to its nearest other point (0 for duplicates)."""
    distances, _ = KDTree(points).query(points, k=2, p=p)
    return np.asarray(distances[:, 1], dtype=np.float64)


class _ObjectiveMetric(DiversityMetric, ABC):
    def __init__(self, ideal: FloatArray, nadir: FloatArray) -> None:
        self.ideal = ideal
        self.nadir = nadir

    def _normalize(self, F: FloatArray) -> FloatArray:
        return _scale(F, self.ideal, self.nadir)


class Spacing(_ObjectiveMetric):
    """Spacing of the first front (Schott, 1995); 0 when evenly spaced (lower is better).

    Standard deviation, with ``n - 1`` in the denominator, of the Manhattan
    distance from each point to its nearest neighbour in the front.
    """

    @property
    def name(self) -> str:
        return "spacing"

    def __call__(self, population: Population, front: FloatArray) -> float | None:
        if front.shape[0] < 2:
            return None
        nearest = _nearest_other(self._normalize(front), p=1.0)
        return float(np.std(nearest, ddof=1))


class GeneralizedSpread(_ObjectiveMetric):
    """Spread Δ of the first front (Deb et al., 2002; generalised by Zhou et al., 2006).

    ``(sum_m d(e_m, S) + sum_i |d_i - mean d|) / (sum_m d(e_m, S) + |S| mean d)``,
    where ``e_m`` is the extreme of the reference front along objective ``m``
    and ``d_i`` the Euclidean distance from each point to its nearest neighbour.
    0 for an evenly spaced front reaching the extremes (lower is better). Only
    nearest-neighbour distances enter it, so gaps between evenly spaced groups
    (e.g. two pairs at the ends of the front) go unnoticed.
    """

    def __init__(self, reference_front: FloatArray, ideal: FloatArray, nadir: FloatArray) -> None:
        super().__init__(ideal, nadir)
        reference = self._normalize(reference_front)
        self.extremes = reference[np.argmax(reference, axis=0)]

    @property
    def name(self) -> str:
        return "spread"

    def __call__(self, population: Population, front: FloatArray) -> float | None:
        if front.shape[0] < 2:
            return None
        points = self._normalize(front)
        to_extremes = float(KDTree(points).query(self.extremes)[0].sum())
        nearest = _nearest_other(points)
        mean = float(nearest.mean())
        denominator = to_extremes + points.shape[0] * mean
        if denominator == 0.0:
            return None
        return float((to_extremes + np.abs(nearest - mean).sum()) / denominator)


class MeanPairwiseDistance(_ObjectiveMetric):
    """Mean Euclidean distance between all pairs of individuals of the population."""

    def __init__(
        self, ideal: FloatArray, nadir: FloatArray, *, block: int = PAIRWISE_BLOCK
    ) -> None:
        super().__init__(ideal, nadir)
        self._block = block

    @property
    def name(self) -> str:
        return "mean_distance"

    def __call__(self, population: Population, front: FloatArray) -> float | None:
        n = len(population)
        if n < 2:
            return None
        points = self._normalize(population.F)
        total = sum(
            float(cdist(points[start : start + self._block], points).sum())
            for start in range(0, n, self._block)
        )
        return total / (n * (n - 1))


class DecisionInertia(DiversityMetric):
    """Moment of inertia of the population in decision space (Morrison and De Jong, 2002).

    Mean squared distance to the centroid of the variables scaled to ``[0, 1]``,
    divided by the number of variables: the mean per-variable variance, between
    0 (all individuals identical) and 0.25.
    """

    def __init__(self, lower: FloatArray, upper: FloatArray) -> None:
        self.lower = lower
        self.upper = upper

    @property
    def name(self) -> str:
        return "decision_inertia"

    def __call__(self, population: Population, front: FloatArray) -> float | None:
        X = _scale(population.X, self.lower, self.upper)
        return float(np.mean(np.var(X, axis=0)))
