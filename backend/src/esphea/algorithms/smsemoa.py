"""SMS-EMOA (Beume, Naujoks and Emmerich, 2007), generational variant."""

from esphea.core.algorithm import EvolutionaryAlgorithm
from esphea.core.operators import Crossover, Mutation, Sampling
from esphea.core.problem import Problem
from esphea.operators import (
    HypervolumeContributionSurvival,
    PolynomialMutation,
    RandomMatingSelection,
    SimulatedBinaryCrossover,
    UniformRandomSampling,
)


class SMSEMOA(EvolutionaryAlgorithm):
    """Indicator-based EMOA: survival by exclusive hypervolume contribution.

    The original algorithm is steady state (one offspring per iteration); here
    each generation produces ``pop_size`` offspring and removes the least
    contributing individuals of ``P_t + Q_t`` one at a time, so generations are
    comparable with NSGA-II and NSGA-III. Parents are drawn uniformly at random,
    as in the original; SBX (eta=15, p=0.9) and polynomial mutation (eta=20,
    p=1/n_var) are the defaults.
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
            selection=RandomMatingSelection(),
            crossover=crossover or SimulatedBinaryCrossover(eta=15.0, prob=0.9),
            mutation=mutation or PolynomialMutation(eta=20.0),
            survival=HypervolumeContributionSurvival(),
        )

    @property
    def name(self) -> str:
        return "SMS-EMOA"
