"""Run-unique identities of individuals across generations."""

import numpy as np

from esphea.core.population import Population
from esphea.core.records import GenerationRecord
from esphea.core.types import IntArray


class IdentityTracker:
    """Assigns every individual of a run a unique, persistent id.

    ``P_0`` receives ids ``0..N-1``; every offspring receives the next unused
    id; survivors keep theirs. The tracker must observe every generation, in
    order, to stay aligned with the population.
    """

    def __init__(self) -> None:
        self._population: IntArray = np.empty(0, dtype=np.int64)
        self._next = 0

    def start(self, initial: Population) -> IntArray:
        self._population = self._fresh(len(initial))
        return self._population

    def advance(self, record: GenerationRecord) -> tuple[IntArray, IntArray]:
        """Ids of ``record.population`` and ``record.offspring``; moves on to the survivors."""
        if len(self._population) != len(record.population):
            raise RuntimeError("identity tracker is out of sync with the population")
        population = self._population
        offspring = self._fresh(len(record.offspring))
        self._population = np.concatenate((population, offspring))[record.survivor_indices]
        return population, offspring

    def _fresh(self, n: int) -> IntArray:
        ids = np.arange(self._next, self._next + n, dtype=np.int64)
        self._next += n
        return ids
