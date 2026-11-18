"""TOPO: problems whose Pareto front has a prescribed shape, and so a known topology.

A platform construction (not from the literature). The points of the hyperplane
``sum f = M / 2`` are mutually non-dominated: if ``a <= b`` componentwise and both sum to
the same value, then ``a = b``. Any closed shape ``S`` drawn on that hyperplane is
therefore a front of its own, provided every other attainable point is dominated by a
point of ``S``. With ``y`` the position variables (coordinates on the hyperplane), ``z``
the distance variables and an orthonormal basis ``B`` of the hyperplane,

    f = c + B y + (g(z) + d(y)) 1,    g(z) = sum((z_j - 0.5)^2),    c = (0.5, ..., 0.5),

where ``d(y)`` is the Euclidean distance from ``y`` to ``S``. A point with ``y`` in ``S``
and ``g > 0`` is dominated by the same ``y`` with ``g = 0``. For ``y`` outside ``S``, let
``s`` be its nearest point of ``S``: ``f(y) - f(s) = B (y - s) + (g + d) 1``. ``B (y - s)``
sums to 0 and has norm ``d``, so none of its components is below
``-d sqrt((M - 1) / M) > -d``. Every component of the difference is positive, and ``s``
dominates ``y``. The front is exactly ``c + B S``, an isometric copy of the shape, so its
homology is the shape's.

Shapes on the plane (three objectives) and in space (four objectives):

=========  ======================================  =============  =========
Shape      Front                                   Betti numbers  Dimension
=========  ======================================  =============  =========
disc       a disc (control)                        1, 0           2
ring       a circle                                1, 1           1
eight      two circles touching at a point         1, 2           1
holes      a disc with ``count`` holes (1-6)       1, count       2
islands    ``count`` disjoint discs (2-8)          count, 0       2
ball       a ball (control)                        1, 0, 0        3
shell      a ball with a cavity                    1, 0, 1        3
sphere     the surface of a ball                   1, 0, 1        2
torus      the surface of a torus                  1, 2, 1        2
=========  ======================================  =============  =========

Positions are drawn uniformly from the box ``[-0.5, 0.5]^(M-1)``, so solutions are not
biased towards any part of the shape (unlike IMOP).
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Literal

import numpy as np

from esphea.core.problem import Problem
from esphea.core.types import FloatArray, frozen

type ShapeName = Literal[
    "disc", "ring", "eight", "holes", "islands", "ball", "shell", "sphere", "torus"
]

COUNT_RANGES: dict[str, tuple[int, int]] = {"holes": (1, 6), "islands": (2, 8)}
"""Shapes that take a count (of holes, of islands), with its smallest and largest value."""

CENTRE = 0.5
"""Every objective of the centre of the shape (the box of positions is centre +- 0.5)."""


def hyperplane_basis(n_obj: int) -> FloatArray:
    """Orthonormal basis (columns) of the hyperplane ``sum f = 0`` (Helmert vectors)."""
    basis = np.zeros((n_obj, n_obj - 1))
    for j in range(n_obj - 1):
        basis[: j + 1, j] = 1.0
        basis[j + 1, j] = -(j + 1.0)
        basis[:, j] /= np.sqrt((j + 1.0) * (j + 2.0))
    return basis


def _norm(y: FloatArray) -> FloatArray:
    norm: FloatArray = np.linalg.norm(y, axis=-1)
    return norm


def _refine(sample: Callable[[float], FloatArray], n_points: int, start: float) -> FloatArray:
    """Sample with a spacing that shrinks until at least ``n_points`` points come out."""
    spacing = start
    while True:
        points = sample(spacing)
        if len(points) >= n_points:
            return points
        spacing *= 0.9


def _lattice(dimension: int, extent: float, spacing: float) -> FloatArray:
    axis = np.arange(-extent, extent + spacing / 2, spacing)
    grid = np.meshgrid(*[axis] * dimension, indexing="ij")
    return np.column_stack([a.ravel() for a in grid])


def _check_count(shape: str, count: int) -> None:
    low, high = COUNT_RANGES[shape]
    if not low <= count <= high:
        raise ValueError(f"the '{shape}' shape takes a count from {low} to {high}, got {count}")


class Shape(ABC):
    """A closed subset of the hyperplane, in coordinates of its orthonormal basis."""

    dimension: int  # of the space it is drawn in (M - 1)
    betti: tuple[int, ...]

    @abstractmethod
    def distance(self, y: FloatArray) -> FloatArray:
        """Euclidean distance from each row of ``y`` to the shape (0 on it)."""

    @abstractmethod
    def sample(self, n_points: int) -> FloatArray:
        """At least ``n_points`` points spread evenly over the shape."""

    @abstractmethod
    def support(self, w: FloatArray) -> float:
        """Largest ``<w, y>`` over the shape."""


class Region(Shape):
    """A shape with an interior: sampled by a lattice clipped to it."""

    extent: float  # the shape fits in the cube [-extent, extent]^dimension

    def sample(self, n_points: int) -> FloatArray:
        def clipped(spacing: float) -> FloatArray:
            points = _lattice(self.dimension, self.extent, spacing)
            inside: FloatArray = points[self.distance(points) == 0.0]
            return inside

        return _refine(clipped, n_points, start=self.extent / 4)


class Disc(Region):
    dimension = 2
    betti = (1, 0)

    def __init__(self, radius: float = 0.4) -> None:
        self.radius = self.extent = radius

    def distance(self, y: FloatArray) -> FloatArray:
        return np.maximum(0.0, _norm(y) - self.radius)

    def support(self, w: FloatArray) -> float:
        return self.radius * float(np.linalg.norm(w))


class Holes(Region):
    """A disc of radius 0.45 with ``count`` round holes of radius 0.1.

    One hole sits in the middle; two to four sit on a circle of radius 0.21; five and six
    are one in the middle and the others on a circle of radius 0.27. The solid parts
    between holes, and between holes and the rim, are at least 0.07 wide.
    """

    dimension = 2
    radius = extent = 0.45
    hole = 0.1

    def __init__(self, count: int) -> None:
        _check_count("holes", count)
        self.betti = (1, count)
        around = count if 2 <= count <= 4 else count - 1
        ring = 0.21 if count <= 4 else 0.27
        angle = np.pi / 2 + 2 * np.pi * np.arange(around) / max(around, 1)
        centres = ring * np.column_stack((np.cos(angle), np.sin(angle)))
        if count in (1, 5, 6):
            centres = np.vstack((np.zeros((1, 2)), centres))
        self.centres = centres

    def distance(self, y: FloatArray) -> FloatArray:
        outside = np.maximum(0.0, _norm(y) - self.radius)
        depth = self.hole - _norm(y[:, None, :] - self.centres[None, :, :])
        inside: FloatArray = np.maximum(0.0, depth.max(axis=1))
        return outside + inside  # at most one is positive

    def support(self, w: FloatArray) -> float:
        return self.radius * float(np.linalg.norm(w))


class Islands(Region):
    """``count`` discs on a circle of radius 0.3 (radius ``min(0.12, 0.3 * chord)``)."""

    dimension = 2
    extent = 0.45

    def __init__(self, count: int) -> None:
        _check_count("islands", count)
        self.betti = (count, 0)
        angle = np.pi / 2 + 2 * np.pi * np.arange(count) / count
        self.centres = 0.3 * np.column_stack((np.cos(angle), np.sin(angle)))
        chord = 2 * 0.3 * np.sin(np.pi / count)
        self.radius = min(0.12, 0.3 * chord)

    def distance(self, y: FloatArray) -> FloatArray:
        gaps = _norm(y[:, None, :] - self.centres[None, :, :]) - self.radius
        distance: FloatArray = np.maximum(0.0, gaps.min(axis=1))
        return distance

    def support(self, w: FloatArray) -> float:
        return float((self.centres @ w).max() + self.radius * np.linalg.norm(w))


class Circles(Shape):
    """Circles of equal radius (a ring, or two touching circles: an eight)."""

    dimension = 2

    def __init__(self, centres: FloatArray, radius: float) -> None:
        self.centres, self.radius = centres, radius
        self.betti = (1, len(centres))

    def distance(self, y: FloatArray) -> FloatArray:
        gaps = np.abs(_norm(y[:, None, :] - self.centres[None, :, :]) - self.radius)
        distance: FloatArray = gaps.min(axis=1)
        return distance

    def sample(self, n_points: int) -> FloatArray:
        per_circle = int(np.ceil(max(n_points, 3) / len(self.centres)))
        angle = 2 * np.pi * np.arange(per_circle) / per_circle
        circle = self.radius * np.column_stack((np.cos(angle), np.sin(angle)))
        return (self.centres[:, None, :] + circle[None, :, :]).reshape(-1, 2)

    def support(self, w: FloatArray) -> float:
        return float((self.centres @ w).max() + self.radius * np.linalg.norm(w))


class Ball(Region):
    """A ball, or a spherical shell when ``inner > 0`` (a cavity: ``beta_2 = 1``)."""

    dimension = 3

    def __init__(self, outer: float = 0.4, inner: float = 0.0) -> None:
        self.inner, self.outer, self.extent = inner, outer, outer
        self.betti = (1, 0, 1 if inner > 0 else 0)

    def distance(self, y: FloatArray) -> FloatArray:
        r = _norm(y)
        return np.maximum(0.0, np.maximum(self.inner - r, r - self.outer))

    def support(self, w: FloatArray) -> float:
        return self.outer * float(np.linalg.norm(w))


class Sphere(Shape):
    dimension = 3
    betti = (1, 0, 1)

    def __init__(self, radius: float = 0.35) -> None:
        self.radius = radius

    def distance(self, y: FloatArray) -> FloatArray:
        return np.abs(_norm(y) - self.radius)

    def sample(self, n_points: int) -> FloatArray:
        """Fibonacci lattice: equal areas per point."""
        n = max(n_points, 4)
        i = np.arange(n) + 0.5
        z = 1 - 2 * i / n
        angle = np.pi * (1 + np.sqrt(5)) * i
        r = np.sqrt(1 - z**2)
        return self.radius * np.column_stack((r * np.cos(angle), r * np.sin(angle), z))

    def support(self, w: FloatArray) -> float:
        return self.radius * float(np.linalg.norm(w))


class Torus(Shape):
    """Surface at distance ``tube`` from the circle of radius ``major`` in the plane z = 0."""

    dimension = 3
    betti = (1, 2, 1)

    def __init__(self, major: float = 0.27, tube: float = 0.12) -> None:
        self.major, self.tube = major, tube

    def distance(self, y: FloatArray) -> FloatArray:
        planar = np.hypot(y[:, 0], y[:, 1]) - self.major
        return np.abs(np.hypot(planar, y[:, 2]) - self.tube)

    def sample(self, n_points: int) -> FloatArray:
        """Equal areas per point: the tube angle follows the area element ``major + tube cos``."""
        n = max(n_points, 16)
        around = int(np.ceil(np.sqrt(n * self.major / self.tube)))
        across = int(np.ceil(n / around))
        # inverse of the cumulative area along the tube, (major v + tube sin v) / (2 pi major)
        dense = np.linspace(0.0, 2 * np.pi, 20_001)
        cumulative = (self.major * dense + self.tube * np.sin(dense)) / (2 * np.pi * self.major)
        v = np.interp((np.arange(across) + 0.5) / across, cumulative, dense)
        u = 2 * np.pi * np.arange(around) / around
        uu, vv = (a.ravel() for a in np.meshgrid(u, v, indexing="ij"))
        radius = self.major + self.tube * np.cos(vv)
        return np.column_stack((radius * np.cos(uu), radius * np.sin(uu), self.tube * np.sin(vv)))

    def support(self, w: FloatArray) -> float:
        # the torus spans the Minkowski sum of its centre circle and a ball of radius tube
        return self.major * float(np.hypot(w[0], w[1])) + self.tube * float(np.linalg.norm(w))


PLANAR_SHAPES: tuple[ShapeName, ...] = ("disc", "ring", "eight", "holes", "islands")
SPATIAL_SHAPES: tuple[ShapeName, ...] = ("ball", "shell", "sphere", "torus")


def shape_objectives(shape: ShapeName) -> int:
    """Objectives of a shape's problem: 3 on the plane, 4 in space."""
    return 3 if shape in PLANAR_SHAPES else 4


_FACTORIES: dict[str, Callable[[int], Shape]] = {
    "disc": lambda _: Disc(),
    "ring": lambda _: Circles(np.zeros((1, 2)), 0.3),
    "eight": lambda _: Circles(np.array([[-0.2, 0.0], [0.2, 0.0]]), 0.2),
    "holes": Holes,
    "islands": Islands,
    "ball": lambda _: Ball(),
    "shell": lambda _: Ball(outer=0.4, inner=0.2),
    "sphere": lambda _: Sphere(),
    "torus": lambda _: Torus(),
}


def make_shape(shape: ShapeName, count: int | None = None) -> Shape:
    if shape not in _FACTORIES:
        raise ValueError(f"unknown shape '{shape}'")
    if shape in COUNT_RANGES and count is None:
        raise ValueError(f"the '{shape}' shape needs a count")
    if shape not in COUNT_RANGES and count is not None:
        raise ValueError(f"the '{shape}' shape takes no count")
    return _FACTORIES[shape](count or 0)


class TOPO(Problem):
    """Front with a prescribed shape on the hyperplane ``sum f = M / 2`` (see the module).

    ``n_var = (M - 1) + k``: ``M - 1`` position variables, mapped to ``[-0.5, 0.5]``, and
    ``k`` distance variables, optimal at 0.5. Planar shapes have three objectives, spatial
    ones four.
    """

    def __init__(self, shape: ShapeName = "holes", count: int | None = 2, k: int = 10) -> None:
        if k < 1:
            raise ValueError(f"k must be positive, got {k}")
        self.shape_name, self.count = shape, count
        self.shape = make_shape(shape, count)
        n_obj = self.shape.dimension + 1
        super().__init__(n_var=n_obj - 1 + k, n_obj=n_obj, lower=0.0, upper=1.0)
        self.k = k
        self.basis = frozen(hyperplane_basis(n_obj))

    @property
    def name(self) -> str:
        return f"TOPO-{self.shape_name}{self.count or ''}"

    def embed(self, y: FloatArray) -> FloatArray:
        """Objective vectors of the positions ``y`` on the front (``g = 0``)."""
        embedded: FloatArray = CENTRE + y @ self.basis.T
        return embedded

    def _evaluate(self, X: FloatArray) -> FloatArray:
        m = self.n_obj
        y = X[:, : m - 1] - 0.5
        g = np.sum((X[:, m - 1 :] - 0.5) ** 2, axis=1)
        return self.embed(y) + (g + self.shape.distance(y))[:, None]

    def pareto_front(self, n_points: int) -> FloatArray:
        return self.embed(self.shape.sample(n_points))

    @property
    def ideal_point(self) -> FloatArray:
        return frozen(np.array([CENTRE - self.shape.support(-row) for row in self.basis]))

    @property
    def nadir_point(self) -> FloatArray:
        return frozen(np.array([CENTRE + self.shape.support(row) for row in self.basis]))
