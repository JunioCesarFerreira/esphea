"""Array type aliases shared across the code base.

Populations are represented as *structures of arrays*: a decision matrix ``X``
of shape ``(n, n_var)`` and an objective matrix ``F`` of shape ``(n, n_obj)``.
This keeps every numerical step vectorised.
"""

from typing import Any

import numpy as np
import numpy.typing as npt

type FloatArray = npt.NDArray[np.float64]
type IntArray = npt.NDArray[np.intp]
type BoolArray = npt.NDArray[np.bool_]
type AnyArray = npt.NDArray[Any]


def frozen[T: np.generic](array: npt.NDArray[T]) -> npt.NDArray[T]:
    """Return ``array`` flagged as read-only, so it can be shared safely."""
    array.flags.writeable = False
    return array
