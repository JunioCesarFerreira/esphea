"""Immutable population container."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

import numpy as np

from esphea.core.types import AnyArray, FloatArray, IntArray, frozen


@dataclass(frozen=True, slots=True)
class Population:
    """A set of solutions stored as aligned arrays.

    Attributes:
        X: Decision matrix, shape ``(n, n_var)``.
        F: Objective matrix, shape ``(n, n_obj)``.
        attributes: Per-individual arrays produced by survival operators
            (e.g. ``rank``, ``crowding``, ``niche``). Each has length ``n``.

    All arrays are read-only. This makes it safe to hand the same population to
    any number of observers without defensive copies.
    """

    X: FloatArray
    F: FloatArray
    attributes: Mapping[str, AnyArray] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.X.ndim != 2 or self.F.ndim != 2:
            raise ValueError("X and F must be two-dimensional")
        if self.X.shape[0] != self.F.shape[0]:
            raise ValueError(f"X has {self.X.shape[0]} rows but F has {self.F.shape[0]}")
        for name, values in self.attributes.items():
            if values.shape[0] != self.X.shape[0]:
                raise ValueError(
                    f"attribute '{name}' has length {values.shape[0]}, expected {len(self)}"
                )
        frozen(self.X)
        frozen(self.F)
        for values in self.attributes.values():
            frozen(values)
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))

    def __len__(self) -> int:
        return int(self.X.shape[0])

    @property
    def n_var(self) -> int:
        return int(self.X.shape[1])

    @property
    def n_obj(self) -> int:
        return int(self.F.shape[1])

    def attribute(self, name: str) -> AnyArray:
        """Return a survival attribute, failing loudly when it is missing."""
        try:
            return self.attributes[name]
        except KeyError:
            available = ", ".join(sorted(self.attributes)) or "none"
            raise KeyError(
                f"population has no attribute '{name}' (available: {available})"
            ) from None

    def take(self, indices: IntArray) -> "Population":
        """Return the sub-population at ``indices`` (attributes included)."""
        return Population(
            X=self.X[indices],
            F=self.F[indices],
            attributes={name: values[indices] for name, values in self.attributes.items()},
        )

    def with_attributes(self, attributes: Mapping[str, AnyArray]) -> "Population":
        """Return the same solutions carrying ``attributes`` instead of the current ones."""
        return Population(X=self.X, F=self.F, attributes=attributes)

    @staticmethod
    def concat(first: "Population", second: "Population") -> "Population":
        """Stack two populations. Attributes are dropped: they are context dependent."""
        return Population(X=np.vstack((first.X, second.X)), F=np.vstack((first.F, second.F)))
