"""Initial population samplers."""

import numpy as np

from esphea.core.operators import Sampling
from esphea.core.problem import Problem
from esphea.core.types import FloatArray


class UniformRandomSampling(Sampling):
    """Independent uniform sampling inside the box constraints."""

    def sample(self, problem: Problem, n: int, rng: np.random.Generator) -> FloatArray:
        return rng.uniform(problem.lower, problem.upper, size=(n, problem.n_var))
