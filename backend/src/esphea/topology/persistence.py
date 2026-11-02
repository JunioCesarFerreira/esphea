"""Persistent homology of point clouds."""

from abc import ABC, abstractmethod

import numpy as np
from ripser import ripser

from esphea.core.types import FloatArray
from esphea.topology.diagram import PersistenceDiagram


class PersistenceComputer(ABC):
    """Computes the persistence diagram of a point cloud up to a maximum scale."""

    @abstractmethod
    def compute(
        self, points: FloatArray, *, max_dimension: int, max_epsilon: float
    ) -> PersistenceDiagram:
        """Diagrams of ``H_0 .. H_max_dimension`` of the filtration on ``points``."""


class VietorisRips(PersistenceComputer):
    """Vietoris-Rips filtration computed with Ripser (Bauer, 2021).

    Convention: the filtration value of a simplex is the length of its longest
    edge (Euclidean distance), i.e. ``epsilon`` is a *diameter*, not a radius.
    In our benchmarks Ripser was 4-20 times faster than GUDHI's Rips complex
    on populations of 100-1000 points, with identical diagrams.
    """

    def compute(
        self, points: FloatArray, *, max_dimension: int, max_epsilon: float
    ) -> PersistenceDiagram:
        if points.ndim != 2 or points.shape[0] == 0:
            raise ValueError("points must be a non-empty (n, d) matrix")
        if max_epsilon <= 0:
            raise ValueError("max_epsilon must be positive")
        result = ripser(
            np.ascontiguousarray(points, dtype=np.float64),
            maxdim=max_dimension,
            thresh=max_epsilon,
        )
        return PersistenceDiagram.from_intervals(result["dgms"], max_epsilon)
