"""NSGA-II (Deb, Pratap, Agarwal and Meyarivan, 2002)."""

from esphea.core.algorithm import EvolutionaryAlgorithm
from esphea.core.operators import Crossover, Mutation, Sampling
from esphea.core.problem import Problem
from esphea.operators import (
    CrowdedBinaryTournament,
    PolynomialMutation,
    RankAndCrowdingSurvival,
    SimulatedBinaryCrossover,
    UniformRandomSampling,
)


class NSGA2(EvolutionaryAlgorithm):
    """Elitist non-dominated sorting GA with crowding distance.

    Defaults follow the original paper: SBX (eta=15, p=0.9) and polynomial
    mutation (eta=20, p=1/n_var). Any operator can be replaced by injection.
    """

    def __init__(
        self,
        problem: Problem,
        pop_size: int = 100,
        *,
        crossover: Crossover | None = None,
        mutation: Mutation | None = None,
        sampling: Sampling | None = None,
    ) -> None:
        super().__init__(
            problem=problem,
            pop_size=pop_size,
            sampling=sampling or UniformRandomSampling(),
            selection=CrowdedBinaryTournament(),
            crossover=crossover or SimulatedBinaryCrossover(eta=15.0, prob=0.9),
            mutation=mutation or PolynomialMutation(eta=20.0),
            survival=RankAndCrowdingSurvival(),
        )

    @property
    def name(self) -> str:
        return "NSGA-II"
