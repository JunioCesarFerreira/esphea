import numpy as np
from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting

from esphea.core import Population
from esphea.operators import (
    HypervolumeContributionSurvival,
    RankAndCrowdingSurvival,
    ReferenceDirectionSurvival,
)
from esphea.problems import DTLZ2, ZDT1
from esphea.reference_directions import das_dennis


def random_candidates(problem: DTLZ2, n: int, rng: np.random.Generator) -> Population:
    X = rng.random((n, problem.n_var))
    return Population(X=X, F=problem.evaluate(X))


def test_rank_and_crowding_keeps_best_fronts(dtlz2: DTLZ2, rng: np.random.Generator) -> None:
    candidates = random_candidates(dtlz2, 200, rng)
    result = RankAndCrowdingSurvival().select(dtlz2, candidates, 100, rng)

    assert result.indices.shape == (100,)
    assert len(np.unique(result.indices)) == 100
    rank = result.attributes["rank"]
    crowding = result.attributes["crowding"]
    assert rank.shape == crowding.shape == (100,)

    true_rank = NonDominatedSorting().do(candidates.F, return_rank=True)[1]
    np.testing.assert_array_equal(rank, true_rank[result.indices])
    # Elitism: nobody discarded has a better rank than the worst survivor.
    discarded = np.setdiff1d(np.arange(200), result.indices)
    assert true_rank[discarded].min() >= rank.max()


def test_reference_direction_survival_attributes(dtlz2: DTLZ2, rng: np.random.Generator) -> None:
    ref_dirs = das_dennis(3, 12)
    candidates = random_candidates(dtlz2, 184, rng)
    result = ReferenceDirectionSurvival(ref_dirs).select(dtlz2, candidates, 92, rng)

    assert len(np.unique(result.indices)) == 92
    assert set(result.attributes) == {"rank", "niche", "dist_to_niche"}
    assert np.all((result.attributes["niche"] >= 0) & (result.attributes["niche"] < 91))
    assert np.all(result.attributes["dist_to_niche"] >= 0.0)


def test_hypervolume_contribution_survival_keeps_best_fronts(
    dtlz2: DTLZ2, rng: np.random.Generator
) -> None:
    candidates = random_candidates(dtlz2, 200, rng)
    result = HypervolumeContributionSurvival().select(dtlz2, candidates, 100, rng)

    assert len(np.unique(result.indices)) == 100
    assert set(result.attributes) == {"rank"}
    true_rank = NonDominatedSorting().do(candidates.F, return_rank=True)[1]
    np.testing.assert_array_equal(result.attributes["rank"], true_rank[result.indices])
    discarded = np.setdiff1d(np.arange(200), result.indices)
    assert true_rank[discarded].min() >= result.attributes["rank"].max()


def test_hypervolume_contribution_survival_drops_the_least_contributor(
    rng: np.random.Generator,
) -> None:
    # Four mutually non-dominated points on a line; one of the two close ones adds the least.
    problem = ZDT1(n_var=2)
    F = np.array([[0.0, 1.0], [0.5, 0.5], [0.52, 0.48], [1.0, 0.0]])
    candidates = Population(X=np.zeros((4, problem.n_var)), F=F)
    result = HypervolumeContributionSurvival().select(problem, candidates, 3, rng)
    assert sorted(result.indices.tolist()) in ([0, 1, 3], [0, 2, 3])
