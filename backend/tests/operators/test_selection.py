import numpy as np

from esphea.core import Population
from esphea.operators import CrowdedBinaryTournament, RandomMatingSelection


def population_with(rank: list[int], crowding: list[float]) -> Population:
    n = len(rank)
    return Population(
        X=np.zeros((n, 2)),
        F=np.zeros((n, 2)),
        attributes={"rank": np.array(rank), "crowding": np.array(crowding)},
    )


def test_random_selection_shape_and_balance(rng: np.random.Generator) -> None:
    pop = population_with([0] * 10, [0.0] * 10)
    matings = RandomMatingSelection().select(pop, n_matings=5, n_parents=2, rng=rng)
    assert matings.shape == (5, 2)
    # 10 slots drawn from one permutation of 10 individuals: each used exactly once.
    np.testing.assert_array_equal(np.sort(matings.ravel()), np.arange(10))


def test_tournament_never_picks_worst_rank_against_better(rng: np.random.Generator) -> None:
    pop = population_with([0, 1], [0.0, 10.0])
    matings = CrowdedBinaryTournament().select(pop, n_matings=50, n_parents=2, rng=rng)
    # Every tournament between 0 and 1 is won by 0; ties (0 vs 0 or 1 vs 1) are
    # impossible here because candidates come from permutations of two individuals.
    assert np.all(matings == 0)


def test_tournament_breaks_rank_ties_by_crowding(rng: np.random.Generator) -> None:
    pop = population_with([0, 0], [1.0, np.inf])
    matings = CrowdedBinaryTournament().select(pop, n_matings=50, n_parents=2, rng=rng)
    assert np.all(matings == 1)


def test_tournament_full_ties_are_random(rng: np.random.Generator) -> None:
    pop = population_with([0, 0], [1.0, 1.0])
    matings = CrowdedBinaryTournament().select(pop, n_matings=500, n_parents=2, rng=rng)
    share = np.mean(matings == 0)
    assert 0.4 < share < 0.6
