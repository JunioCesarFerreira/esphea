"""Real-coded variation operators backed by pymoo's vectorised kernels."""

import numpy as np
from pymoo.operators.crossover.sbx import cross_sbx
from pymoo.operators.mutation.pm import mut_pm

from esphea.core.operators import Crossover, Mutation, Offspring
from esphea.core.problem import Problem
from esphea.core.types import FloatArray, IntArray


def _check_probability(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must lie in [0, 1], got {value}")


class SimulatedBinaryCrossover(Crossover):
    """Simulated binary crossover (Deb and Agrawal, 1995).

    Args:
        eta: Distribution index; larger values keep children closer to parents.
        prob: Probability that a mating undergoes crossover (otherwise the
            children are copies of the parents).
        prob_var: Per-variable probability of recombination within a mating.

    Child ``c`` of mating ``m`` is stored at row ``c * n_matings + m``; the
    lineage returned in :class:`Offspring` follows that layout.
    """

    def __init__(self, eta: float = 15.0, prob: float = 0.9, prob_var: float = 0.5) -> None:
        if eta <= 0:
            raise ValueError(f"eta must be positive, got {eta}")
        _check_probability("prob", prob)
        _check_probability("prob_var", prob_var)
        self.eta = eta
        self.prob = prob
        self.prob_var = prob_var

    @property
    def n_parents(self) -> int:
        return 2

    @property
    def n_offspring_per_mating(self) -> int:
        return 2

    def cross(
        self,
        problem: Problem,
        X: FloatArray,
        matings: IntArray,
        rng: np.random.Generator,
    ) -> Offspring:
        n_matings = matings.shape[0]
        parents_X = np.swapaxes(X[matings], 0, 1)  # (2, n_matings, n_var)
        column = np.ones((n_matings, 1))
        children = cross_sbx(
            parents_X.astype(np.float64),
            problem.lower,
            problem.upper,
            column * self.eta,
            column * self.prob_var,
            column * 0.5,  # probability of swapping the two children per variable
            random_state=rng,
        )
        skip = rng.random(n_matings) >= self.prob
        children[:, skip] = parents_X[:, skip]
        child_X = children.reshape(-1, problem.n_var)
        lineage = np.tile(matings, (self.n_offspring_per_mating, 1))
        return Offspring(X=child_X, parents=lineage.astype(np.intp))


class PolynomialMutation(Mutation):
    """Polynomial mutation (Deb and Goyal, 1996).

    Args:
        eta: Distribution index; larger values produce smaller perturbations.
        prob_var: Per-variable mutation probability; ``None`` means ``1 / n_var``.
    """

    def __init__(self, eta: float = 20.0, prob_var: float | None = None) -> None:
        if eta <= 0:
            raise ValueError(f"eta must be positive, got {eta}")
        if prob_var is not None:
            _check_probability("prob_var", prob_var)
        self.eta = eta
        self.prob_var = prob_var

    def mutate(self, problem: Problem, X: FloatArray, rng: np.random.Generator) -> FloatArray:
        n = X.shape[0]
        prob_var = 1.0 / problem.n_var if self.prob_var is None else self.prob_var
        mutated = mut_pm(
            X.astype(np.float64, copy=True),
            problem.lower,
            problem.upper,
            np.full(n, self.eta),
            np.full(n, prob_var),
            at_least_once=False,
            random_state=rng,
        )
        return np.asarray(mutated, dtype=np.float64)
