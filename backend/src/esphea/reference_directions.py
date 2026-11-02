"""Structured reference directions (Das and Dennis, 1998)."""

from math import comb

import numpy as np
from pymoo.util.ref_dirs import get_reference_directions

from esphea.core.types import FloatArray


def das_dennis_count(n_obj: int, n_partitions: int) -> int:
    """Number of Das-Dennis points: ``C(p + M - 1, M - 1)``."""
    return comb(n_partitions + n_obj - 1, n_obj - 1)


def das_dennis(n_obj: int, n_partitions: int) -> FloatArray:
    """Uniformly spaced points on the unit simplex, shape ``(H, n_obj)``."""
    if n_obj < 1 or n_partitions < 1:
        raise ValueError("n_obj and n_partitions must be positive")
    directions = get_reference_directions("das-dennis", n_obj, n_partitions=n_partitions)
    return np.asarray(directions, dtype=np.float64)


def das_dennis_partitions_for(n_obj: int, n_points: int) -> int:
    """Smallest number of partitions yielding at least ``n_points`` directions."""
    partitions = 1
    while das_dennis_count(n_obj, partitions) < n_points:
        partitions += 1
    return partitions


def nsga3_population_size(n_directions: int) -> int:
    """Smallest multiple of four not below ``n_directions`` (Deb and Jain, 2014)."""
    return -(-n_directions // 4) * 4
