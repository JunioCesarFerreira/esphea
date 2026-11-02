"""Data emitted by the evolutionary loop at every generation."""

from dataclasses import dataclass

import numpy as np

from esphea.core.population import Population
from esphea.core.types import BoolArray, IntArray


@dataclass(frozen=True, slots=True)
class GenerationRecord:
    """Complete account of one generation ``t -> t + 1``.

    This is the main object of study of the project: it exposes the parent
    pool, the mating decisions, the offspring with their lineage and the
    survivors, so any analysis (e.g. persistent homology) can be attached as an
    observer without touching the algorithms.

    Attributes:
        generation: Index ``t + 1`` of the generation being produced (1-based).
        population: Parent pool ``P_t`` (with the attributes of the previous survival).
        matings: ``(n_matings, n_parents)`` indices into ``population``.
        offspring: Offspring population ``Q_t``.
        offspring_parents: ``(n_offspring, n_parents)`` indices into ``population``.
        mutated: Whether mutation changed each offspring.
        survivor_indices: Indices of ``P_{t+1}`` within ``merged = P_t + Q_t``.
        survivors: Next population ``P_{t+1}`` with its survival attributes.
    """

    generation: int
    population: Population
    matings: IntArray
    offspring: Population
    offspring_parents: IntArray
    mutated: BoolArray
    survivor_indices: IntArray
    survivors: Population

    def merged(self) -> Population:
        """Candidate population ``P_t + Q_t`` seen by the survival operator."""
        return Population.concat(self.population, self.offspring)

    def survived_mask(self) -> BoolArray:
        """Boolean mask over :meth:`merged` marking the survivors."""
        mask = np.zeros(len(self.population) + len(self.offspring), dtype=np.bool_)
        mask[self.survivor_indices] = True
        return mask

    def times_selected(self) -> IntArray:
        """Number of matings each individual of ``population`` took part in."""
        return np.bincount(self.matings.ravel(), minlength=len(self.population)).astype(np.intp)
