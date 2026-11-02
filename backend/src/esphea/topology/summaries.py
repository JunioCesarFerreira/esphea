"""Scalar and functional summaries of persistence diagrams (vectorised)."""

import numpy as np

from esphea.core.types import BoolArray, FloatArray, IntArray


def betti_curve(bars: FloatArray, truncated: BoolArray, grid: FloatArray) -> IntArray:
    """Number of features alive at each scale of ``grid``.

    A feature ``[b, d)`` is alive at ``eps`` when ``b <= eps < d``; truncated
    features are alive up to and including the maximum scale.
    """
    if bars.shape[0] == 0:
        return np.zeros(grid.shape[0], dtype=np.intp)
    born = bars[:, :1] <= grid
    alive = (grid < bars[:, 1:]) | truncated[:, None]
    return np.asarray((born & alive).sum(axis=0), dtype=np.intp)


def total_persistence(bars: FloatArray) -> float:
    """Sum of the bar lengths."""
    return float(np.sum(bars[:, 1] - bars[:, 0]))


def persistent_entropy(bars: FloatArray) -> float:
    """Shannon entropy of the normalised bar lengths (Chintakunta et al., 2015).

    0 for a single dominant feature, ``log(n)`` for ``n`` equally persistent ones.
    """
    lengths = bars[:, 1] - bars[:, 0]
    lengths = lengths[lengths > 0]
    if lengths.shape[0] == 0:
        return 0.0
    p = lengths / lengths.sum()
    return float(-np.sum(p * np.log(p)))
