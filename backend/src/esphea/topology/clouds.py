"""Point clouds extracted from stored generations, and their normalisation."""

from abc import ABC, abstractmethod
from enum import StrEnum

import numpy as np

from esphea.core.problem import KnownParetoFront, Problem
from esphea.core.types import FloatArray
from esphea.experiments.storage import GenerationSnapshot


class PointCloudKind(StrEnum):
    SURVIVORS = "survivors"
    MERGED = "merged"
    FIRST_FRONT = "first_front"


class PointCloudSelector(ABC):
    """Chooses which individuals of a stored generation ``g`` form the point cloud.

    A snapshot of generation ``g`` holds the parent pool ``P_{g-1}``, the offspring
    ``Q_{g-1}`` and which of them survived into ``P_g`` (generation 0 holds ``P_0``).
    """

    @abstractmethod
    def select(self, snapshot: GenerationSnapshot) -> FloatArray:
        """Objective vectors of the cloud, shape ``(n, n_obj)``."""


class Survivors(PointCloudSelector):
    """The population ``P_g``."""

    def select(self, snapshot: GenerationSnapshot) -> FloatArray:
        groups = [snapshot.population, snapshot.offspring]
        return np.vstack([g.F[g.survived] for g in groups if g is not None])


class Merged(PointCloudSelector):
    """The candidates ``P_{g-1} + Q_{g-1}`` the survival selected from (``P_0`` for g = 0)."""

    def select(self, snapshot: GenerationSnapshot) -> FloatArray:
        groups = [snapshot.population, snapshot.offspring]
        return np.vstack([g.F for g in groups if g is not None])


class FirstFront(PointCloudSelector):
    """The non-dominated members of ``P_g`` (survival rank 0)."""

    def select(self, snapshot: GenerationSnapshot) -> FloatArray:
        groups = [snapshot.population, snapshot.offspring]
        return np.vstack([g.F[g.survived & (g.rank == 0)] for g in groups if g is not None])


SELECTORS: dict[PointCloudKind, PointCloudSelector] = {
    PointCloudKind.SURVIVORS: Survivors(),
    PointCloudKind.MERGED: Merged(),
    PointCloudKind.FIRST_FRONT: FirstFront(),
}


class NormalizationKind(StrEnum):
    NONE = "none"
    IDEAL_NADIR = "ideal_nadir"
    MIN_MAX = "min_max"


class Normalizer(ABC):
    @abstractmethod
    def transform(self, points: FloatArray) -> FloatArray: ...


class Identity(Normalizer):
    """Raw objective values: scale changes (e.g. convergence) show in the diagrams."""

    def transform(self, points: FloatArray) -> FloatArray:
        return points


class FixedScaling(Normalizer):
    """Affine map sending ``ideal`` to 0 and ``nadir`` to 1, identical for every generation."""

    def __init__(self, ideal: FloatArray, nadir: FloatArray) -> None:
        span = nadir - ideal
        if np.any(span <= 0):
            raise ValueError("nadir must exceed ideal in every objective")
        self._ideal = ideal
        self._span = span

    def transform(self, points: FloatArray) -> FloatArray:
        return (points - self._ideal) / self._span


class PerCloudMinMax(Normalizer):
    """Each cloud scaled to its own bounding box: isolates shape from scale."""

    def transform(self, points: FloatArray) -> FloatArray:
        low = points.min(axis=0)
        span = points.max(axis=0) - low
        return (points - low) / np.where(span > 0, span, 1.0)


def build_normalizer(kind: NormalizationKind, problem: Problem) -> Normalizer:
    """Normaliser of ``kind``; ``IDEAL_NADIR`` needs a problem with a known front."""
    if kind == NormalizationKind.NONE:
        return Identity()
    if kind == NormalizationKind.MIN_MAX:
        return PerCloudMinMax()
    if not isinstance(problem, KnownParetoFront):
        raise ValueError(f"{problem.name} has no known ideal and nadir points")
    return FixedScaling(problem.ideal_point, problem.nadir_point)
