"""Registries that turn configuration models into domain objects.

Supporting a new problem or algorithm means writing its config model and a
builder, then registering it; nothing else in the pipeline changes.
"""

from collections.abc import Callable
from typing import Any

from esphea.algorithms import NSGA2, NSGA3
from esphea.core.algorithm import EvolutionaryAlgorithm
from esphea.core.problem import Problem
from esphea.experiments.config import (
    DTLZ2Config,
    NSGA2Config,
    NSGA3Config,
    PMConfig,
    SBXConfig,
)
from esphea.operators import PolynomialMutation, SimulatedBinaryCrossover
from esphea.problems import DTLZ2
from esphea.reference_directions import das_dennis

type ProblemBuilder = Callable[[Any], Problem]
type AlgorithmBuilder = Callable[[Any, Problem], EvolutionaryAlgorithm]


class ProblemRegistry:
    def __init__(self) -> None:
        self._builders: dict[str, ProblemBuilder] = {}

    def register(self, name: str, builder: ProblemBuilder) -> None:
        if name in self._builders:
            raise ValueError(f"problem '{name}' is already registered")
        self._builders[name] = builder

    def names(self) -> list[str]:
        return sorted(self._builders)

    def build(self, config: Any) -> Problem:
        name: str = config.name
        try:
            builder = self._builders[name]
        except KeyError:
            raise KeyError(f"unknown problem '{name}'") from None
        return builder(config)


class AlgorithmRegistry:
    def __init__(self) -> None:
        self._builders: dict[str, AlgorithmBuilder] = {}

    def register(self, name: str, builder: AlgorithmBuilder) -> None:
        if name in self._builders:
            raise ValueError(f"algorithm '{name}' is already registered")
        self._builders[name] = builder

    def names(self) -> list[str]:
        return sorted(self._builders)

    def build(self, config: Any, problem: Problem) -> EvolutionaryAlgorithm:
        name: str = config.name
        try:
            builder = self._builders[name]
        except KeyError:
            raise KeyError(f"unknown algorithm '{name}'") from None
        return builder(config, problem)


# --- default builders -----------------------------------------------------------------


def _sbx(config: SBXConfig) -> SimulatedBinaryCrossover:
    return SimulatedBinaryCrossover(eta=config.eta, prob=config.prob, prob_var=config.prob_var)


def _pm(config: PMConfig) -> PolynomialMutation:
    return PolynomialMutation(eta=config.eta, prob_var=config.prob_var)


def _build_dtlz2(config: DTLZ2Config) -> Problem:
    return DTLZ2(n_obj=config.n_obj, k=config.k)


def _build_nsga2(config: NSGA2Config, problem: Problem) -> EvolutionaryAlgorithm:
    return NSGA2(
        problem,
        pop_size=config.pop_size,
        crossover=_sbx(config.crossover),
        mutation=_pm(config.mutation),
    )


def _build_nsga3(config: NSGA3Config, problem: Problem) -> EvolutionaryAlgorithm:
    return NSGA3(
        problem,
        ref_dirs=das_dennis(problem.n_obj, config.n_partitions),
        pop_size=config.pop_size,
        crossover=_sbx(config.crossover),
        mutation=_pm(config.mutation),
    )


def default_problem_registry() -> ProblemRegistry:
    registry = ProblemRegistry()
    registry.register("dtlz2", _build_dtlz2)
    return registry


def default_algorithm_registry() -> AlgorithmRegistry:
    registry = AlgorithmRegistry()
    registry.register("nsga2", _build_nsga2)
    registry.register("nsga3", _build_nsga3)
    return registry
