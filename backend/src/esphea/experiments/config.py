"""Declarative, validated experiment configuration.

These models are the single source of truth for what an experiment is: the
API accepts them, the database stores them as JSON and the worker rebuilds the
exact same objects from them.
"""

from typing import Annotated, Literal, Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from esphea.reference_directions import das_dennis_count, nsga3_population_size

MAX_REFERENCE_DIRECTIONS = 20_000
MAX_SEED = 2**32 - 1


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --- problems -------------------------------------------------------------------------


class DTLZ2Config(_Model):
    name: Literal["dtlz2"] = "dtlz2"
    n_obj: int = Field(default=3, ge=2, le=15, description="Number of objectives (M).")
    k: int = Field(default=10, ge=1, le=100, description="Distance variables; n_var = M + k - 1.")

    @property
    def n_var(self) -> int:
        return self.n_obj + self.k - 1


class _ZDTConfig(_Model):
    n_obj: Literal[2] = Field(default=2, description="ZDT problems are bi-objective.")
    n_var: int = Field(default=30, ge=2, le=1000, description="Decision variables (n).")


class ZDT1Config(_ZDTConfig):
    """Convex, connected front."""

    name: Literal["zdt1"] = "zdt1"


class ZDT3Config(_ZDTConfig):
    """Disconnected front (five pieces)."""

    name: Literal["zdt3"] = "zdt3"


class ZDT4Config(_ZDTConfig):
    """Convex front behind many local fronts (multimodal)."""

    name: Literal["zdt4"] = "zdt4"
    n_var: int = Field(default=10, ge=2, le=1000, description="Decision variables (n).")


ProblemConfig = Annotated[
    DTLZ2Config | ZDT1Config | ZDT3Config | ZDT4Config, Field(discriminator="name")
]


# --- variation operators --------------------------------------------------------------


class SBXConfig(_Model):
    eta: float = Field(default=15.0, gt=0, le=1000, description="Distribution index.")
    prob: float = Field(default=0.9, ge=0, le=1, description="Probability of crossover per mating.")
    prob_var: float = Field(
        default=0.5, ge=0, le=1, description="Per-variable recombination probability."
    )


class PMConfig(_Model):
    eta: float = Field(default=20.0, gt=0, le=1000, description="Distribution index.")
    prob_var: float | None = Field(
        default=None, ge=0, le=1, description="Per-variable probability; null means 1/n_var."
    )


# --- algorithms -----------------------------------------------------------------------


class NSGA2Config(_Model):
    name: Literal["nsga2"] = "nsga2"
    pop_size: int = Field(default=100, ge=4, le=10_000)
    crossover: SBXConfig = SBXConfig(eta=15.0, prob=0.9)
    mutation: PMConfig = PMConfig(eta=20.0)

    def resolved_pop_size(self, n_obj: int) -> int:
        return self.pop_size


class NSGA3Config(_Model):
    name: Literal["nsga3"] = "nsga3"
    n_partitions: int = Field(
        default=12, ge=1, le=200, description="Das-Dennis partitions (p) of the unit simplex."
    )
    pop_size: int | None = Field(
        default=None,
        ge=4,
        le=10_000,
        description="Null means the smallest multiple of 4 not below the number of directions.",
    )
    crossover: SBXConfig = SBXConfig(eta=30.0, prob=1.0)
    mutation: PMConfig = PMConfig(eta=20.0)

    def n_reference_directions(self, n_obj: int) -> int:
        return das_dennis_count(n_obj, self.n_partitions)

    def resolved_pop_size(self, n_obj: int) -> int:
        if self.pop_size is not None:
            return self.pop_size
        return nsga3_population_size(self.n_reference_directions(n_obj))


AlgorithmConfig = Annotated[NSGA2Config | NSGA3Config, Field(discriminator="name")]


# --- observation ----------------------------------------------------------------------


class MetricsConfig(_Model):
    gd: bool = True
    igd: bool = True
    igd_plus: bool = True
    hv: bool = True
    every: int = Field(default=1, ge=1, description="Compute indicators every N generations.")
    reference_front_size: int = Field(
        default=1000, ge=10, le=100_000, description="Points sampled from the true front."
    )


class SnapshotConfig(_Model):
    enabled: bool = True
    every: int = Field(default=1, ge=1, description="Store every N-th generation.")
    precision: Literal["float32", "float64"] = "float64"
    decision_variables: bool = Field(
        default=True, description="Also store X (objectives F are always stored)."
    )


# --- experiment -----------------------------------------------------------------------


class ExperimentConfig(_Model):
    name: str = Field(min_length=1, max_length=120)
    problem: ProblemConfig = DTLZ2Config()
    algorithm: AlgorithmConfig
    n_gen: int = Field(default=250, ge=1, le=100_000)
    n_runs: int = Field(default=1, ge=1, le=100, description="Independent runs (seeds).")
    seed: int = Field(default=0, ge=0, le=MAX_SEED, description="Base seed of the experiment.")
    metrics: MetricsConfig = MetricsConfig()
    snapshots: SnapshotConfig = SnapshotConfig()

    @model_validator(mode="after")
    def _check_algorithm_against_problem(self) -> Self:
        algorithm = self.algorithm
        if isinstance(algorithm, NSGA3Config):
            n_dirs = algorithm.n_reference_directions(self.problem.n_obj)
            if n_dirs > MAX_REFERENCE_DIRECTIONS:
                raise ValueError(
                    f"{n_dirs} reference directions (M={self.problem.n_obj}, "
                    f"p={algorithm.n_partitions}) exceed the limit of {MAX_REFERENCE_DIRECTIONS}"
                )
            if algorithm.pop_size is not None and algorithm.pop_size < n_dirs:
                raise ValueError(
                    f"NSGA-III pop_size ({algorithm.pop_size}) must not be below the "
                    f"number of reference directions ({n_dirs})"
                )
        return self

    @property
    def pop_size(self) -> int:
        return self.algorithm.resolved_pop_size(self.problem.n_obj)

    def run_seeds(self) -> list[int]:
        """Independent, reproducible seeds for each run, derived from :attr:`seed`."""
        children = np.random.SeedSequence(self.seed).spawn(self.n_runs)
        return [int(child.generate_state(1, dtype=np.uint32)[0]) for child in children]

    def estimated_snapshot_bytes(self) -> int:
        """Upper bound (uncompressed) of the snapshot storage of one run."""
        if not self.snapshots.enabled:
            return 0
        stored_generations = self.n_gen // self.snapshots.every + 1
        rows = stored_generations * 2 * self.pop_size
        width = self.problem.n_obj + (
            self.problem.n_var if self.snapshots.decision_variables else 0
        )
        value_bytes = 4 if self.snapshots.precision == "float32" else 8
        bookkeeping = 4 + 1 + 4 + 1 + 4 + 2 + 4 + 4 + 1  # see storage.SNAPSHOT_SCHEMA
        return rows * (width * value_bytes + bookkeeping)
