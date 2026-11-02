"""Optimisation problem abstractions."""

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

import numpy as np

from esphea.core.types import FloatArray, frozen


class Problem(ABC):
    """Box-constrained multi-objective minimisation problem.

    Subclasses implement :meth:`_evaluate`, which receives a whole population at
    once and must be vectorised. :meth:`evaluate` validates shapes around it
    (template method), so implementations can focus on the mathematics.
    """

    def __init__(
        self,
        n_var: int,
        n_obj: int,
        lower: FloatArray | float,
        upper: FloatArray | float,
    ) -> None:
        if n_var < 1:
            raise ValueError(f"n_var must be positive, got {n_var}")
        if n_obj < 1:
            raise ValueError(f"n_obj must be positive, got {n_obj}")
        lower_arr = np.broadcast_to(np.asarray(lower, dtype=np.float64), (n_var,)).copy()
        upper_arr = np.broadcast_to(np.asarray(upper, dtype=np.float64), (n_var,)).copy()
        if np.any(lower_arr > upper_arr):
            raise ValueError("every lower bound must be <= its upper bound")
        self._n_var = n_var
        self._n_obj = n_obj
        self._lower = frozen(lower_arr)
        self._upper = frozen(upper_arr)

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable identifier, e.g. ``"DTLZ2"``."""

    @property
    def n_var(self) -> int:
        return self._n_var

    @property
    def n_obj(self) -> int:
        return self._n_obj

    @property
    def lower(self) -> FloatArray:
        return self._lower

    @property
    def upper(self) -> FloatArray:
        return self._upper

    def evaluate(self, X: FloatArray) -> FloatArray:
        """Evaluate a ``(n, n_var)`` decision matrix into a ``(n, n_obj)`` objective matrix."""
        if X.ndim != 2 or X.shape[1] != self._n_var:
            raise ValueError(f"expected X with shape (n, {self._n_var}), got {X.shape}")
        F = self._evaluate(X)
        if F.shape != (X.shape[0], self._n_obj):
            raise RuntimeError(
                f"{self.name} returned F with shape {F.shape}, expected {(X.shape[0], self._n_obj)}"
            )
        return F

    @abstractmethod
    def _evaluate(self, X: FloatArray) -> FloatArray:
        """Vectorised objective computation (shapes already validated)."""


@runtime_checkable
class KnownParetoFront(Protocol):
    """Capability of problems whose Pareto front is analytically known.

    Kept separate from :class:`Problem` (interface segregation): quality
    indicators that need a reference front depend only on this protocol.
    """

    def pareto_front(self, n_points: int) -> FloatArray:
        """Return approximately ``n_points`` points well spread over the Pareto front."""
        ...

    @property
    def ideal_point(self) -> FloatArray: ...

    @property
    def nadir_point(self) -> FloatArray: ...
