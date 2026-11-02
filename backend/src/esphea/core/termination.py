"""Termination criteria."""

from abc import ABC, abstractmethod
from collections.abc import Sequence


class Termination(ABC):
    """Decides, before each generation, whether the run must stop."""

    @abstractmethod
    def should_stop(self, generation: int) -> bool:
        """``generation`` is the number of generations already completed."""


class MaxGenerations(Termination):
    def __init__(self, n_gen: int) -> None:
        if n_gen < 0:
            raise ValueError(f"n_gen must be non-negative, got {n_gen}")
        self.n_gen = n_gen

    def should_stop(self, generation: int) -> bool:
        return generation >= self.n_gen


class AnyOf(Termination):
    """Stops as soon as any of the wrapped criteria does."""

    def __init__(self, criteria: Sequence[Termination]) -> None:
        self._criteria = tuple(criteria)

    def should_stop(self, generation: int) -> bool:
        return any(criterion.should_stop(generation) for criterion in self._criteria)
