"""IMOP problems: three-objective benchmarks with irregular Pareto fronts.

Y. Tian, R. Cheng, X. Zhang, M. Li and Y. Jin. Diversity assessment of multi-objective
evolutionary algorithms: performance metric and benchmark problems. IEEE Computational
Intelligence Magazine 14(3): 61-74, 2019. The definitions follow the authors' implementation
in PlatEMO (K = 5, a1 = 0.05, a2 = 10).

Every problem has ``n_var`` variables in [0, 1]: the first ``K = 5`` set the position on the
front and the others the distance to it, through ``g = sum((x_j - 0.5)^2)`` (0 on the Pareto
set). The positions pass through ``y_1 = mean(x_1, x_3, x_5)^0.05`` and
``y_2 = mean(x_2, x_4)^10`` (IMOP4: ``y = mean(x_1..x_5)^0.05``), which crowd uniform samples
near ``y_1 = 1`` and ``y_2 = 0``: solutions are spread very unevenly over the front.

==========  =================================================  ===================
Problem     Front                                              Topology
==========  =================================================  ===================
IMOP4       a wavy curve                                       one 1-D piece
IMOP5       eight discs on the plane ``sum f = 0.5``           8 pieces
IMOP6       a square grid of strips on a plane                 one piece, 9 holes
IMOP7       three bands of the unit sphere that meet           one piece (a star)
IMOP8       a 10 x 10 array of patches (as DTLZ7)              100 pieces
==========  =================================================  ===================
"""

from abc import abstractmethod
from collections.abc import Callable
from functools import cached_property

import numpy as np

from esphea.core.problem import Problem
from esphea.core.types import BoolArray, FloatArray, frozen
from esphea.problems.dtlz import separable_front, separable_optimal_values
from esphea.reference_directions import das_dennis

IMOP_K = 5
IMOP_A1 = 0.05
IMOP_A2 = 10.0
CURVE_RESOLUTION = 100_001


class IMOP(Problem):
    """Common structure: three objectives, ``K`` position variables, the rest distance ones."""

    def __init__(self, n_var: int = 10) -> None:
        if n_var <= IMOP_K:
            raise ValueError(f"IMOP problems need more than {IMOP_K} variables, got {n_var}")
        super().__init__(n_var=n_var, n_obj=3, lower=0.0, upper=1.0)

    @staticmethod
    def _g(X: FloatArray) -> FloatArray:
        g: FloatArray = np.sum((X[:, IMOP_K:] - 0.5) ** 2, axis=1)
        return g

    @staticmethod
    def _y(X: FloatArray) -> tuple[FloatArray, FloatArray]:
        y1 = X[:, 0:IMOP_K:2].mean(axis=1) ** IMOP_A1
        y2 = X[:, 1:IMOP_K:2].mean(axis=1) ** IMOP_A2
        return y1, y2

    # every IMOP problem knows its front (``KnownParetoFront``)

    @abstractmethod
    def pareto_front(self, n_points: int) -> FloatArray: ...

    @property
    @abstractmethod
    def ideal_point(self) -> FloatArray: ...

    @property
    @abstractmethod
    def nadir_point(self) -> FloatArray: ...


def _refine(sample: Callable[[int], FloatArray], n_points: int, start: int) -> FloatArray:
    """Sample at growing resolutions until at least ``n_points`` points come out."""
    resolution = start
    while True:
        points = sample(resolution)
        if len(points) >= n_points:
            return points
        resolution = int(np.ceil(resolution * 1.1)) + 1


class IMOP4(IMOP):
    """Degenerate front: the curve ``(y, y + sin(10 pi y) / 10, 1 - y)``, ``y`` in [0, 1].

    ``f_1`` grows and ``f_3`` falls along the curve, so its points are mutually non-dominated;
    ``g > 0`` scales a point of the curve by ``1 + g`` (``f_2 >= 0`` on the curve).
    """

    @property
    def name(self) -> str:
        return "IMOP4"

    @staticmethod
    def _curve(y: FloatArray) -> FloatArray:
        return np.column_stack((y, y + np.sin(10.0 * np.pi * y) / 10.0, 1.0 - y))

    def _evaluate(self, X: FloatArray) -> FloatArray:
        y = X[:, :IMOP_K].mean(axis=1) ** IMOP_A1
        return self._curve(y) * (1.0 + self._g(X))[:, None]

    @cached_property
    def _dense(self) -> FloatArray:
        return frozen(self._curve(np.linspace(0.0, 1.0, CURVE_RESOLUTION)))

    def pareto_front(self, n_points: int) -> FloatArray:
        """Points equally spaced along the curve (by arc length)."""
        dense = self._dense
        length = np.concatenate(([0.0], np.cumsum(np.linalg.norm(np.diff(dense, axis=0), axis=1))))
        target = np.linspace(0.0, length[-1], max(n_points, 2))
        y = np.interp(target, length, np.linspace(0.0, 1.0, CURVE_RESOLUTION))
        return self._curve(y)

    @property
    def ideal_point(self) -> FloatArray:
        return frozen(self._dense.min(axis=0))

    @property
    def nadir_point(self) -> FloatArray:
        return frozen(self._dense.max(axis=0))


IMOP5_RING = 0.4
IMOP5_RADIUS = 0.1


class IMOP5(IMOP):
    """Eight discs of radius 0.1 on the plane ``f_3 = 0.5 - f_1 - f_2``.

    ``ceil(8 y_1)`` picks the disc, centred at ``0.4 (cos(k pi / 4), sin(k pi / 4))`` in
    ``(f_1, f_2)``; ``0.1 y_2`` and ``16 pi y_1`` give the radius and the angle within it.
    The points of the plane are mutually non-dominated and ``g`` is added to every objective.
    """

    @property
    def name(self) -> str:
        return "IMOP5"

    @staticmethod
    def centres() -> FloatArray:
        angle = np.arange(1, 9) * np.pi / 4.0
        return IMOP5_RING * np.column_stack((np.cos(angle), np.sin(angle)))

    def _evaluate(self, X: FloatArray) -> FloatArray:
        y1, y2 = self._y(X)
        sector = np.pi * np.ceil(8.0 * y1) / 4.0
        f1 = IMOP5_RING * np.cos(sector) + IMOP5_RADIUS * y2 * np.cos(16.0 * np.pi * y1)
        f2 = IMOP5_RING * np.sin(sector) + IMOP5_RADIUS * y2 * np.sin(16.0 * np.pi * y1)
        F = np.column_stack((f1, f2, 0.5 - f1 - f2))
        return F + self._g(X)[:, None]

    def pareto_front(self, n_points: int) -> FloatArray:
        """A square lattice clipped to each disc (uniform over the area)."""

        def lattice(resolution: int) -> FloatArray:
            axis = np.linspace(-IMOP5_RADIUS, IMOP5_RADIUS, resolution)
            disc = np.stack(np.meshgrid(axis, axis), axis=-1).reshape(-1, 2)
            disc = disc[np.linalg.norm(disc, axis=1) <= IMOP5_RADIUS]
            f = (self.centres()[:, None, :] + disc[None, :, :]).reshape(-1, 2)
            return np.column_stack((f, 0.5 - f.sum(axis=1)))

        return _refine(lattice, n_points, start=4)

    def _extent(self, direction: FloatArray) -> float:
        """Largest ``<direction, (f_1, f_2)>`` over the discs."""
        return float((self.centres() @ direction).max() + IMOP5_RADIUS * np.linalg.norm(direction))

    @property
    def ideal_point(self) -> FloatArray:
        e1, e2, ones = np.array([1.0, 0.0]), np.array([0.0, 1.0]), np.ones(2)
        return frozen(np.array([-self._extent(-e1), -self._extent(-e2), 0.5 - self._extent(ones)]))

    @property
    def nadir_point(self) -> FloatArray:
        e1, e2, ones = np.array([1.0, 0.0]), np.array([0.0, 1.0]), np.ones(2)
        return frozen(np.array([self._extent(e1), self._extent(e2), 0.5 + self._extent(-ones)]))


IMOP6_STRIP = 0.05
"""Points with ``min(sin^2(3 pi y_1), sin^2(3 pi y_2))`` above this value are lifted off."""


class IMOP6(IMOP):
    """A grid of strips on the plane ``f_3 = 1 - (f_1 + f_2) / 2``: one piece with nine holes.

    The front is ``(y_1, y_2, 1 - (y_1 + y_2) / 2)`` where ``y_1`` or ``y_2`` lies within
    ``arcsin(sqrt(0.05)) / (3 pi) ~ 0.024`` of 0, 1/3, 2/3 or 1. The rest of the plane is
    lifted by 1 in every objective, so it is dominated: the nine open squares between the
    strips are the holes.
    """

    @property
    def name(self) -> str:
        return "IMOP6"

    @staticmethod
    def _closeness(y1: FloatArray, y2: FloatArray) -> FloatArray:
        """``min(sin^2(3 pi y_1), sin^2(3 pi y_2))``: small near the lines of the grid."""
        closeness: FloatArray = np.minimum(
            np.sin(3.0 * np.pi * y1) ** 2, np.sin(3.0 * np.pi * y2) ** 2
        )
        return closeness

    @classmethod
    def on_strips(cls, y1: FloatArray, y2: FloatArray) -> BoolArray:
        on: BoolArray = cls._closeness(y1, y2) <= IMOP6_STRIP
        return on

    def _evaluate(self, X: FloatArray) -> FloatArray:
        y1, y2 = self._y(X)
        g = self._g(X)
        lift = np.ceil(np.maximum(0.0, self._closeness(y1, y2) - IMOP6_STRIP))  # 0 or 1
        F = np.column_stack(((1.0 + g) * y1, (1.0 + g) * y2, (0.5 + g) * (2.0 - y1 - y2)))
        return F + lift[:, None]

    def pareto_front(self, n_points: int) -> FloatArray:
        def lattice(resolution: int) -> FloatArray:
            axis = np.linspace(0.0, 1.0, resolution)
            y1, y2 = (a.ravel() for a in np.meshgrid(axis, axis))
            keep = self.on_strips(y1, y2)
            y1, y2 = y1[keep], y2[keep]
            return np.column_stack((y1, y2, 1.0 - (y1 + y2) / 2.0))

        return _refine(lattice, n_points, start=32)

    @property
    def ideal_point(self) -> FloatArray:
        return frozen(np.zeros(3))

    @property
    def nadir_point(self) -> FloatArray:
        return frozen(np.ones(3))


IMOP7_BAND = 0.1
"""Points of the sphere whose objectives all differ by more than this are lifted off."""


class IMOP7(IMOP):
    """Three bands of the unit sphere around ``f_1 = f_2``, ``f_2 = f_3`` and ``f_3 = f_1``.

    The bands follow the three medians of the octant and meet at its centre: a star with six
    arms, one piece without holes. A point whose objectives all differ by ``r > 0.1`` is
    lifted by ``10 (r - 0.1)`` in every objective, which a nearby point of a band dominates.
    """

    @property
    def name(self) -> str:
        return "IMOP7"

    @staticmethod
    def spread(F: FloatArray) -> FloatArray:
        """Smallest difference between two objectives."""
        spread: FloatArray = np.minimum(
            np.minimum(np.abs(F[:, 0] - F[:, 1]), np.abs(F[:, 1] - F[:, 2])),
            np.abs(F[:, 2] - F[:, 0]),
        )
        return spread

    def _evaluate(self, X: FloatArray) -> FloatArray:
        y1, y2 = self._y(X)
        a, b = y1 * np.pi / 2.0, y2 * np.pi / 2.0
        F = np.column_stack((np.cos(a) * np.cos(b), np.cos(a) * np.sin(b), np.sin(a)))
        F *= (1.0 + self._g(X))[:, None]
        return F + 10.0 * np.maximum(0.0, self.spread(F) - IMOP7_BAND)[:, None]

    def pareto_front(self, n_points: int) -> FloatArray:
        def directions(resolution: int) -> FloatArray:
            points = das_dennis(3, resolution)
            points = points / np.linalg.norm(points, axis=1, keepdims=True)
            return points[self.spread(points) <= IMOP7_BAND]

        return _refine(directions, n_points, start=12)

    @property
    def ideal_point(self) -> FloatArray:
        return frozen(np.zeros(3))

    @property
    def nadir_point(self) -> FloatArray:
        return frozen(np.ones(3))


class IMOP8(IMOP):
    """DTLZ7-like front with ``sin(19 pi f)``: ten intervals per axis, 100 pieces.

    ``f_1 = y_1``, ``f_2 = y_2`` and ``f_3 = 3 (1 + g) - phi(f_1) - phi(f_2)`` with
    ``phi(f) = f (1 + sin(19 pi f))``; as for DTLZ7, a point is Pareto optimal iff ``f_1``
    and ``f_2`` both exceed ``phi`` at every smaller value.
    """

    @property
    def name(self) -> str:
        return "IMOP8"

    @staticmethod
    def _phi(f: FloatArray) -> FloatArray:
        phi: FloatArray = f * (1.0 + np.sin(19.0 * np.pi * f))
        return phi

    def _evaluate(self, X: FloatArray) -> FloatArray:
        y1, y2 = self._y(X)
        g = self._g(X)
        f3 = 3.0 * (1.0 + g) - self._phi(y1) - self._phi(y2)
        return np.column_stack((y1, y2, f3))

    @cached_property
    def _optimal_coordinates(self) -> FloatArray:
        return separable_optimal_values(self._phi)

    def pareto_front(self, n_points: int) -> FloatArray:
        f = separable_front(self._optimal_coordinates, 2, n_points)
        return np.column_stack((f, 3.0 - np.sum(self._phi(f), axis=1)))

    @property
    def ideal_point(self) -> FloatArray:
        best = float(self._phi(self._optimal_coordinates).max())
        return frozen(np.array([0.0, 0.0, 3.0 - 2.0 * best]))

    @property
    def nadir_point(self) -> FloatArray:
        far = float(self._optimal_coordinates.max())
        return frozen(np.array([far, far, 3.0]))


__all__ = ["IMOP", "IMOP4", "IMOP5", "IMOP6", "IMOP7", "IMOP8"]
