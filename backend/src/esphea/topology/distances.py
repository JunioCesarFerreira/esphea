"""Distances between persistence diagrams and between point clouds."""

from abc import ABC, abstractmethod

import gudhi
import gudhi.hera
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.distance import directed_hausdorff, pdist

from esphea.core.types import FloatArray

WASSERSTEIN_RELATIVE_ERROR = 1e-4


class DiagramDistance(ABC):
    """Distance between two diagrams of the same homology dimension.

    Inputs are ``(n, 2)`` arrays of finite (birth, death) pairs; unmatched
    points are matched to the diagonal.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier used for storage and display."""

    @abstractmethod
    def __call__(self, first: FloatArray, second: FloatArray) -> float: ...


class BottleneckDistance(DiagramDistance):
    """Bottleneck distance (exact, GUDHI): the largest discrepancy of the best matching."""

    @property
    def name(self) -> str:
        return "bottleneck"

    def __call__(self, first: FloatArray, second: FloatArray) -> float:
        return float(gudhi.bottleneck_distance(first, second, 0))


class WassersteinDistance(DiagramDistance):
    """q-Wasserstein distance (Hera, via GUDHI): sums all discrepancies of the best matching.

    Uses the L-infinity ground metric, consistent with the bottleneck distance
    (which is its limit for q -> infinity).
    """

    def __init__(self, order: float = 1.0) -> None:
        if order < 1:
            raise ValueError("order must be >= 1")
        self.order = order

    @property
    def name(self) -> str:
        return f"wasserstein_{self.order:g}"

    def __call__(self, first: FloatArray, second: FloatArray) -> float:
        return float(
            gudhi.hera.wasserstein_distance(
                first,
                second,
                order=self.order,
                internal_p=np.inf,
                delta=WASSERSTEIN_RELATIVE_ERROR,
            )
        )


def hausdorff_distance(first: FloatArray, second: FloatArray) -> float:
    """Symmetric Hausdorff distance between two point clouds.

    By the stability theorem of Vietoris-Rips persistence,
    ``bottleneck(D(X), D(Y)) <= 2 * hausdorff(X, Y)``.
    """
    return float(max(directed_hausdorff(first, second)[0], directed_hausdorff(second, first)[0]))


def diameter(points: FloatArray) -> float:
    """Largest pairwise distance (0 for a single point)."""
    if points.shape[0] < 2:
        return 0.0
    return float(pdist(points).max())


def nearest_neighbour_distances(points: FloatArray) -> FloatArray:
    """Distance from each point to its nearest other point."""
    if points.shape[0] < 2:
        return np.zeros(points.shape[0])
    distances, _ = cKDTree(points).query(points, k=2)
    return np.asarray(distances[:, 1], dtype=np.float64)
