"""Glue between the ESPHEA domain and pymoo's internal API.

Everything that touches pymoo objects lives here or in the adapter classes, so
a pymoo upgrade (or its replacement) is confined to the ``operators`` package.
"""

from pymoo.core.problem import Problem as PymooProblem

from esphea.core.problem import Problem


def as_pymoo_problem(problem: Problem) -> PymooProblem:
    """Bounds-only pymoo problem; pymoo operators never evaluate it."""
    return PymooProblem(
        n_var=problem.n_var,
        n_obj=problem.n_obj,
        xl=problem.lower.copy(),
        xu=problem.upper.copy(),
    )
