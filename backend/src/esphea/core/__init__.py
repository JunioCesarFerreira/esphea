"""Domain core: problems, populations, operator interfaces and the evolutionary loop."""

from esphea.core.algorithm import EvolutionaryAlgorithm, RunResult
from esphea.core.observer import AlgorithmObserver, CompositeObserver
from esphea.core.operators import (
    Crossover,
    MatingSelection,
    Mutation,
    Offspring,
    Sampling,
    Survival,
    SurvivalResult,
)
from esphea.core.population import Population
from esphea.core.problem import KnownParetoFront, Problem
from esphea.core.records import GenerationRecord
from esphea.core.termination import AnyOf, MaxGenerations, Termination

__all__ = [
    "AlgorithmObserver",
    "AnyOf",
    "CompositeObserver",
    "Crossover",
    "EvolutionaryAlgorithm",
    "GenerationRecord",
    "KnownParetoFront",
    "MatingSelection",
    "MaxGenerations",
    "Mutation",
    "Offspring",
    "Population",
    "Problem",
    "RunResult",
    "Sampling",
    "Survival",
    "SurvivalResult",
    "Termination",
]
