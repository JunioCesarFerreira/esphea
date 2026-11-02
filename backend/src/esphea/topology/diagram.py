"""Persistence diagrams of filtrations truncated at a maximum scale."""

from dataclasses import dataclass

import numpy as np

from esphea.core.types import BoolArray, FloatArray, frozen


@dataclass(frozen=True, slots=True)
class PersistenceDiagram:
    """Barcodes per homology dimension of a filtration computed up to ``max_epsilon``.

    ``bars[k]`` is a ``(n_k, 2)`` array of (birth, death) pairs for ``H_k``.
    Features still alive at ``max_epsilon`` (including the essential class of
    ``H_0``) are *truncated*: their death is set to ``max_epsilon`` and they are
    flagged in ``truncated[k]``. Every value is therefore finite, which keeps
    distances between diagrams computed with the same ``max_epsilon`` finite
    and comparable.
    """

    max_epsilon: float
    bars: tuple[FloatArray, ...]
    truncated: tuple[BoolArray, ...]

    def __post_init__(self) -> None:
        if len(self.bars) != len(self.truncated):
            raise ValueError("bars and truncated must cover the same dimensions")
        for k, (bars, truncated) in enumerate(zip(self.bars, self.truncated, strict=True)):
            if bars.ndim != 2 or bars.shape[1] != 2 or truncated.shape != (bars.shape[0],):
                raise ValueError(f"malformed bars for H_{k}")
            frozen(bars)
            frozen(truncated)

    @property
    def max_dimension(self) -> int:
        return len(self.bars) - 1

    @classmethod
    def from_intervals(
        cls, intervals: list[FloatArray], max_epsilon: float
    ) -> "PersistenceDiagram":
        """Build from raw intervals where unfinished features die at ``+inf``."""
        bars: list[FloatArray] = []
        truncated: list[BoolArray] = []
        for raw in intervals:
            pairs = np.asarray(raw, dtype=np.float64).reshape(-1, 2)
            cut = pairs[:, 1] > max_epsilon
            bars.append(np.column_stack((pairs[:, 0], np.where(cut, max_epsilon, pairs[:, 1]))))
            truncated.append(cut)
        return cls(max_epsilon=max_epsilon, bars=tuple(bars), truncated=tuple(truncated))

    def lifetimes(self, dimension: int) -> FloatArray:
        bars = self.bars[dimension]
        return bars[:, 1] - bars[:, 0]
