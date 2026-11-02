import pytest
from pydantic import ValidationError

from esphea.experiments.config import (
    DTLZ2Config,
    ExperimentConfig,
    NSGA2Config,
    NSGA3Config,
)


def test_defaults_follow_the_papers() -> None:
    config = ExperimentConfig(name="x", algorithm=NSGA3Config())
    assert config.problem.n_var == 12
    assert config.pop_size == 92
    assert config.algorithm.crossover.eta == 30.0
    assert NSGA2Config().crossover.eta == 15.0


def test_algorithm_is_discriminated_by_name() -> None:
    config = ExperimentConfig.model_validate(
        {"name": "x", "algorithm": {"name": "nsga2", "pop_size": 40}}
    )
    assert isinstance(config.algorithm, NSGA2Config)
    assert config.pop_size == 40


def test_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        ExperimentConfig.model_validate({"name": "x", "algorithm": {"name": "nsga2", "foo": 1}})


def test_nsga3_population_must_cover_reference_directions() -> None:
    with pytest.raises(ValidationError, match="reference directions"):
        ExperimentConfig(name="x", algorithm=NSGA3Config(n_partitions=12, pop_size=50))


def test_nsga3_reference_direction_explosion_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exceed the limit"):
        ExperimentConfig(
            name="x", problem=DTLZ2Config(n_obj=10), algorithm=NSGA3Config(n_partitions=12)
        )


def test_run_seeds_are_reproducible_and_distinct() -> None:
    config = ExperimentConfig(name="x", algorithm=NSGA2Config(), n_runs=5, seed=42)
    seeds = config.run_seeds()
    assert seeds == config.run_seeds()
    assert len(set(seeds)) == 5
    other = config.model_copy(update={"seed": 43}).run_seeds()
    assert seeds != other


def test_snapshot_estimate_scales_with_precision_and_frequency() -> None:
    base = ExperimentConfig(name="x", algorithm=NSGA2Config(), n_gen=100)
    half = base.model_copy(
        update={"snapshots": base.snapshots.model_copy(update={"precision": "float32"})}
    )
    sparse = base.model_copy(update={"snapshots": base.snapshots.model_copy(update={"every": 10})})
    assert half.estimated_snapshot_bytes() < base.estimated_snapshot_bytes()
    assert sparse.estimated_snapshot_bytes() < base.estimated_snapshot_bytes() / 5
