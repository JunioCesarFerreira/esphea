"""Environmental selection operators backed by pymoo (compiled non-dominated sorting)."""

from collections.abc import Mapping
from typing import ClassVar

import numpy as np
from pymoo.algorithms.moo.nsga3 import ReferenceDirectionSurvival as PymooReferenceSurvival
from pymoo.core.population import Population as PymooPopulation
from pymoo.core.survival import Survival as PymooSurvival
from pymoo.operators.survival.rank_and_crowding import RankAndCrowding

from esphea.core.operators import Survival, SurvivalResult
from esphea.core.population import Population
from esphea.core.problem import Problem
from esphea.core.types import FloatArray
from esphea.operators._pymoo import as_pymoo_problem


class _PymooSurvivalAdapter(Survival):
    """Runs a pymoo survival operator and reads back indices and attributes."""

    _attribute_dtypes: ClassVar[Mapping[str, type[np.generic]]] = {}

    def __init__(self, delegate: PymooSurvival) -> None:
        self._delegate = delegate

    def select(
        self,
        problem: Problem,
        candidates: Population,
        n_survive: int,
        rng: np.random.Generator,
    ) -> SurvivalResult:
        pymoo_pop = PymooPopulation.new("X", candidates.X, "F", candidates.F)
        indices = np.asarray(
            self._delegate.do(
                as_pymoo_problem(problem),
                pymoo_pop,
                n_survive=n_survive,
                random_state=rng,
                return_indices=True,
            ),
            dtype=np.intp,
        )
        survivors = pymoo_pop[indices]
        attributes = {
            name: np.asarray(survivors.get(name), dtype=dtype)
            for name, dtype in self._attribute_dtypes.items()
        }
        return SurvivalResult(indices=indices, attributes=attributes)


class RankAndCrowdingSurvival(_PymooSurvivalAdapter):
    """NSGA-II survival: non-dominated fronts, last front truncated by crowding distance.

    Survivor attributes: ``rank`` (front index, 0 = non-dominated) and
    ``crowding`` (crowding distance within the front; ``inf`` at boundaries).
    """

    _attribute_dtypes: ClassVar[Mapping[str, type[np.generic]]] = {
        "rank": np.intp,
        "crowding": np.float64,
    }

    def __init__(self) -> None:
        super().__init__(RankAndCrowding(crowding_func="cd"))


class ReferenceDirectionSurvival(_PymooSurvivalAdapter):
    """NSGA-III survival: non-dominated fronts, last front filled by reference-point niching.

    Stateful (adaptive normalisation), so use one instance per run.

    Survivor attributes: ``rank``, ``niche`` (index of the associated reference
    direction) and ``dist_to_niche`` (perpendicular distance to it).
    """

    _attribute_dtypes: ClassVar[Mapping[str, type[np.generic]]] = {
        "rank": np.intp,
        "niche": np.intp,
        "dist_to_niche": np.float64,
    }

    def __init__(self, ref_dirs: FloatArray) -> None:
        super().__init__(PymooReferenceSurvival(ref_dirs))
        self.ref_dirs = ref_dirs
