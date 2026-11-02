"""Mating selection strategies (vectorised)."""

import numpy as np

from esphea.core.operators import MatingSelection
from esphea.core.population import Population
from esphea.core.types import IntArray


def _random_pairs(n: int, n_matings: int, n_parents: int, rng: np.random.Generator) -> IntArray:
    """Draw candidate indices from concatenated permutations (each individual is
    used as evenly as possible, as in pymoo's tournament selection)."""
    needed = n_matings * n_parents
    n_perms = -(-needed // n)
    perms = np.concatenate([rng.permutation(n) for _ in range(n_perms)])[:needed]
    return perms.reshape(n_matings, n_parents).astype(np.intp)


class RandomMatingSelection(MatingSelection):
    """Parents drawn uniformly at random (NSGA-III without constraints)."""

    def select(
        self,
        population: Population,
        n_matings: int,
        n_parents: int,
        rng: np.random.Generator,
    ) -> IntArray:
        return _random_pairs(len(population), n_matings, n_parents, rng)


class CrowdedBinaryTournament(MatingSelection):
    """Binary tournament with the crowded-comparison operator (NSGA-II).

    The winner has the lower non-domination ``rank``; ties are broken by the
    larger ``crowding`` distance and, if still tied, at random. Requires both
    attributes on the population (set by
    :class:`~esphea.operators.survival.RankAndCrowdingSurvival`).
    """

    def select(
        self,
        population: Population,
        n_matings: int,
        n_parents: int,
        rng: np.random.Generator,
    ) -> IntArray:
        rank = population.attribute("rank")
        crowding = population.attribute("crowding")
        contestants = _random_pairs(len(population), n_matings * n_parents, 2, rng)
        a, b = contestants[:, 0], contestants[:, 1]
        coin = rng.random(len(a)) < 0.5
        a_wins = (rank[a] < rank[b]) | (
            (rank[a] == rank[b])
            & ((crowding[a] > crowding[b]) | ((crowding[a] == crowding[b]) & coin))
        )
        winners = np.where(a_wins, a, b)
        return winners.reshape(n_matings, n_parents).astype(np.intp)
