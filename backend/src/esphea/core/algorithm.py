"""Generational (mu + lambda) evolutionary loop."""

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from esphea.core.observer import AlgorithmObserver, CompositeObserver
from esphea.core.operators import Crossover, MatingSelection, Mutation, Sampling, Survival
from esphea.core.population import Population
from esphea.core.problem import Problem
from esphea.core.records import GenerationRecord
from esphea.core.termination import Termination


@dataclass(frozen=True, slots=True)
class RunResult:
    final: Population
    generations: int


class EvolutionaryAlgorithm:
    """Elitist generational EA assembled from strategies.

    One generation is: mating selection -> crossover -> mutation -> evaluation
    -> environmental selection over ``P_t + Q_t``. Concrete algorithms such as
    NSGA-II and NSGA-III differ only in the strategies they inject.

    The loop can be driven at once with :meth:`run` or step by step with
    :meth:`initialize` and :meth:`step` (useful in notebooks).
    """

    def __init__(
        self,
        *,
        problem: Problem,
        pop_size: int,
        sampling: Sampling,
        selection: MatingSelection,
        crossover: Crossover,
        mutation: Mutation,
        survival: Survival,
        n_offspring: int | None = None,
    ) -> None:
        if pop_size < 2:
            raise ValueError(f"pop_size must be at least 2, got {pop_size}")
        n_offspring = pop_size if n_offspring is None else n_offspring
        if n_offspring < 1:
            raise ValueError(f"n_offspring must be positive, got {n_offspring}")
        self.problem = problem
        self.pop_size = pop_size
        self.n_offspring = n_offspring
        self.sampling = sampling
        self.selection = selection
        self.crossover = crossover
        self.mutation = mutation
        self.survival = survival

    @property
    def name(self) -> str:
        return type(self).__name__

    @property
    def n_matings(self) -> int:
        per_mating = self.crossover.n_offspring_per_mating
        return -(-self.n_offspring // per_mating)  # ceiling division

    def initialize(self, rng: np.random.Generator) -> Population:
        """Sample, evaluate and rank ``P_0``."""
        X = self.sampling.sample(self.problem, self.pop_size, rng)
        candidates = Population(X=X, F=self.problem.evaluate(X))
        result = self.survival.select(self.problem, candidates, self.pop_size, rng)
        return candidates.take(result.indices).with_attributes(result.attributes)

    def step(
        self, population: Population, generation: int, rng: np.random.Generator
    ) -> GenerationRecord:
        """Produce generation ``generation`` from ``population``."""
        matings = self.selection.select(population, self.n_matings, self.crossover.n_parents, rng)
        children = self.crossover.cross(self.problem, population.X, matings, rng)
        X_off = children.X[: self.n_offspring]
        parents = children.parents[: self.n_offspring]
        X_mut = self.mutation.mutate(self.problem, X_off, rng)
        mutated = np.any(X_mut != X_off, axis=1)
        offspring = Population(X=X_mut, F=self.problem.evaluate(X_mut))

        merged = Population.concat(population, offspring)
        result = self.survival.select(self.problem, merged, self.pop_size, rng)
        survivors = merged.take(result.indices).with_attributes(result.attributes)
        return GenerationRecord(
            generation=generation,
            population=population,
            matings=matings,
            offspring=offspring,
            offspring_parents=parents,
            mutated=mutated,
            survivor_indices=result.indices,
            survivors=survivors,
        )

    def run(
        self,
        termination: Termination,
        rng: np.random.Generator,
        observers: Sequence[AlgorithmObserver] = (),
    ) -> RunResult:
        """Run until ``termination`` says stop, notifying ``observers`` along the way."""
        observer = CompositeObserver(observers)
        population = self.initialize(rng)
        observer.on_start(population)
        generation = 0
        while not termination.should_stop(generation):
            generation += 1
            record = self.step(population, generation, rng)
            observer.on_generation(record)
            population = record.survivors
        observer.on_finish(population, generation)
        return RunResult(final=population, generations=generation)
