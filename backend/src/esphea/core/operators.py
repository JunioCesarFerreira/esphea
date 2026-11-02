"""Strategy interfaces for the building blocks of a generational EA.

Each step of the evolutionary loop is an injectable strategy, so new
algorithms are built by composition rather than by modifying the loop
(open/closed and dependency-inversion principles).
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from esphea.core.population import Population
from esphea.core.problem import Problem
from esphea.core.types import AnyArray, FloatArray, IntArray


class Sampling(ABC):
    """Creates the initial decision matrix."""

    @abstractmethod
    def sample(self, problem: Problem, n: int, rng: np.random.Generator) -> FloatArray:
        """Return a ``(n, problem.n_var)`` matrix within the problem bounds."""


class MatingSelection(ABC):
    """Chooses which individuals of the current population become parents."""

    @abstractmethod
    def select(
        self,
        population: Population,
        n_matings: int,
        n_parents: int,
        rng: np.random.Generator,
    ) -> IntArray:
        """Return a ``(n_matings, n_parents)`` matrix of indices into ``population``."""


@dataclass(frozen=True, slots=True)
class Offspring:
    """Decision vectors produced by a crossover together with their lineage.

    Attributes:
        X: Offspring decision matrix, shape ``(n_offspring, n_var)``.
        parents: Indices into the parent population, shape ``(n_offspring, n_parents)``.
    """

    X: FloatArray
    parents: IntArray


class Crossover(ABC):
    """Recombines groups of parents into offspring."""

    @property
    @abstractmethod
    def n_parents(self) -> int:
        """Number of parents consumed by one mating."""

    @property
    @abstractmethod
    def n_offspring_per_mating(self) -> int:
        """Number of children produced by one mating."""

    @abstractmethod
    def cross(
        self,
        problem: Problem,
        X: FloatArray,
        matings: IntArray,
        rng: np.random.Generator,
    ) -> Offspring:
        """Recombine the rows of ``X`` selected by ``matings``."""


class Mutation(ABC):
    """Perturbs decision vectors."""

    @abstractmethod
    def mutate(self, problem: Problem, X: FloatArray, rng: np.random.Generator) -> FloatArray:
        """Return a mutated copy of ``X`` (the input must not be modified)."""


@dataclass(frozen=True, slots=True)
class SurvivalResult:
    """Outcome of environmental selection.

    Attributes:
        indices: Indices of the survivors in the candidate population.
        attributes: Per-survivor arrays aligned with ``indices`` (e.g. ``rank``).
    """

    indices: IntArray
    attributes: Mapping[str, AnyArray] = field(default_factory=dict)


class Survival(ABC):
    """Environmental selection: reduces a candidate population to the next generation.

    Implementations may be stateful across generations (e.g. NSGA-III keeps its
    normalisation history), so one instance must serve a single run.
    """

    @abstractmethod
    def select(
        self,
        problem: Problem,
        candidates: Population,
        n_survive: int,
        rng: np.random.Generator,
    ) -> SurvivalResult:
        """Choose ``n_survive`` individuals from ``candidates``."""
