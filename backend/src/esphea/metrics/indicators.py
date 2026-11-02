"""Quality indicators for approximation sets (backed by moocore's C implementations)."""

from abc import ABC, abstractmethod

import moocore
import numpy as np

from esphea.core.types import BoolArray, FloatArray

EXACT_HYPERVOLUME_MAX_OBJECTIVES = 6
"""Above this dimension exact hypervolume becomes prohibitively slow per generation."""


def non_dominated_mask(F: FloatArray) -> BoolArray:
    """Mask of the points of ``F`` not dominated by any other (minimisation)."""
    return np.asarray(moocore.is_nondominated(F), dtype=np.bool_)


class QualityIndicator(ABC):
    """Maps an approximation set ``F`` of shape ``(n, n_obj)`` to a scalar."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier used for storage and display (e.g. ``"igd"``)."""

    @abstractmethod
    def __call__(self, F: FloatArray) -> float:
        """Compute the indicator; lower or higher is better depending on the indicator."""


class _ReferenceFrontIndicator(QualityIndicator, ABC):
    def __init__(self, reference_front: FloatArray) -> None:
        if reference_front.ndim != 2 or reference_front.shape[0] == 0:
            raise ValueError("reference_front must be a non-empty (n, n_obj) matrix")
        self.reference_front = reference_front


class IGD(_ReferenceFrontIndicator):
    """Inverted generational distance (lower is better)."""

    @property
    def name(self) -> str:
        return "igd"

    def __call__(self, F: FloatArray) -> float:
        return float(moocore.igd(F, ref=self.reference_front))


class IGDPlus(_ReferenceFrontIndicator):
    """IGD+ (Ishibuchi et al., 2015), weakly Pareto compliant (lower is better)."""

    @property
    def name(self) -> str:
        return "igd_plus"

    def __call__(self, F: FloatArray) -> float:
        return float(moocore.igd_plus(F, ref=self.reference_front))


class Hypervolume(QualityIndicator):
    """Hypervolume dominated by ``F`` and bounded by ``reference_point`` (higher is better).

    Exact for up to :data:`EXACT_HYPERVOLUME_MAX_OBJECTIVES` objectives and
    approximated deterministically (moocore ``Rphi-FWE+``) beyond that.
    """

    def __init__(self, reference_point: FloatArray) -> None:
        self.reference_point = reference_point
        self.exact = reference_point.shape[0] <= EXACT_HYPERVOLUME_MAX_OBJECTIVES

    @property
    def name(self) -> str:
        return "hv"

    def __call__(self, F: FloatArray) -> float:
        inside = F[np.all(self.reference_point > F, axis=1)]
        if inside.shape[0] == 0:
            return 0.0
        if self.exact:
            return float(moocore.hypervolume(inside, ref=self.reference_point))
        return float(moocore.hv_approx(inside, ref=self.reference_point))
