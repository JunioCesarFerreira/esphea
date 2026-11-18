"""Betti numbers of a sampled front, read from the persistence of its alpha complex."""

import gudhi
import numpy as np

from esphea.core.types import FloatArray


def persistent_betti(points: FloatArray, *, born_by: float, alive_at: float) -> tuple[int, ...]:
    """Per dimension, the bars born by scale ``born_by`` and still alive at ``alive_at``.

    Scales are radii (gudhi's alpha filtration uses squared radii). Pick ``born_by`` above the
    spacing of the sample and ``alive_at`` below the size of the features: the counts are then
    the Betti numbers of the sampled shape.
    """
    tree = gudhi.AlphaComplex(points=np.asarray(points, dtype=np.float64)).create_simplex_tree()
    tree.compute_persistence()
    return tuple(
        sum(
            1
            for birth, death in tree.persistence_intervals_in_dimension(dimension)
            if birth <= born_by**2 and death >= alive_at**2
        )
        for dimension in range(points.shape[1])
    )
