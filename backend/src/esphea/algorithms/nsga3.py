"""NSGA-III (Deb and Jain, 2014)."""

from esphea.core.algorithm import EvolutionaryAlgorithm
from esphea.core.operators import Crossover, Mutation, Sampling
from esphea.core.problem import Problem
from esphea.core.types import FloatArray
from esphea.operators import (
    PolynomialMutation,
    RandomMatingSelection,
    ReferenceDirectionSurvival,
    SimulatedBinaryCrossover,
    UniformRandomSampling,
)
from esphea.reference_directions import nsga3_population_size


class NSGA3(EvolutionaryAlgorithm):
    """Reference-point based many-objective NSGA.

    Defaults follow Deb and Jain (2014): random mating, SBX (eta=30, p=1) and
    polynomial mutation (eta=20, p=1/n_var). The population size defaults to
    the smallest multiple of four not below the number of reference directions.
    """

    def __init__(
        self,
        problem: Problem,
        ref_dirs: FloatArray,
        pop_size: int | None = None,
        *,
        crossover: Crossover | None = None,
        mutation: Mutation | None = None,
        sampling: Sampling | None = None,
    ) -> None:
        if ref_dirs.ndim != 2 or ref_dirs.shape[1] != problem.n_obj:
            raise ValueError(f"ref_dirs must have shape (H, {problem.n_obj}), got {ref_dirs.shape}")
        n_dirs = ref_dirs.shape[0]
        pop_size = nsga3_population_size(n_dirs) if pop_size is None else pop_size
        if pop_size < n_dirs:
            raise ValueError(
                f"pop_size ({pop_size}) must not be below the number of "
                f"reference directions ({n_dirs})"
            )
        super().__init__(
            problem=problem,
            pop_size=pop_size,
            sampling=sampling or UniformRandomSampling(),
            selection=RandomMatingSelection(),
            crossover=crossover or SimulatedBinaryCrossover(eta=30.0, prob=1.0),
            mutation=mutation or PolynomialMutation(eta=20.0),
            survival=ReferenceDirectionSurvival(ref_dirs),
        )
        self.ref_dirs = ref_dirs

    @property
    def name(self) -> str:
        return "NSGA-III"
