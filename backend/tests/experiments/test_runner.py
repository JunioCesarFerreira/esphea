from pathlib import Path

import pytest

from esphea.experiments.config import (
    ExperimentConfig,
    MetricsConfig,
    NSGA2Config,
    NSGA3Config,
    ZDT1Config,
    ZDT3Config,
    ZDT4Config,
)
from esphea.experiments.observers import GenerationMetrics, RunProgress
from esphea.experiments.registry import default_algorithm_registry, default_problem_registry
from esphea.experiments.runner import RunExecutor
from esphea.experiments.storage import SnapshotReader


class ListSink:
    def __init__(self) -> None:
        self.rows: list[GenerationMetrics] = []
        self.flushed = 0

    def add(self, metrics: GenerationMetrics) -> None:
        self.rows.append(metrics)

    def flush(self) -> None:
        self.flushed += 1


class ListReporter:
    def __init__(self) -> None:
        self.events: list[RunProgress] = []

    def report(self, progress: RunProgress) -> None:
        self.events.append(progress)


@pytest.fixture
def executor() -> RunExecutor:
    return RunExecutor(default_problem_registry(), default_algorithm_registry())


@pytest.mark.parametrize("algorithm", [NSGA2Config(pop_size=24), NSGA3Config(n_partitions=6)])
def test_executes_configured_run(
    executor: RunExecutor, tmp_path: Path, algorithm: NSGA2Config | NSGA3Config
) -> None:
    config = ExperimentConfig(
        name="t", algorithm=algorithm, n_gen=10, metrics=MetricsConfig(every=4)
    )
    sink, reporter = ListSink(), ListReporter()
    outcome = executor.execute(
        config, seed=1, metrics_sink=sink, progress=reporter, snapshot_dir=tmp_path / "s"
    )

    assert outcome.generations == 10
    assert not outcome.cancelled
    assert [m.generation for m in sink.rows] == [0, 4, 8, 10]
    assert set(sink.rows[-1].values) == {"igd", "igd_plus", "hv"}
    assert sink.flushed == 1
    assert reporter.events[0].generation == 0
    assert reporter.events[-1].generation == 10
    assert reporter.events[-1].front.shape[1] == 3
    assert SnapshotReader(tmp_path / "s").generations() == list(range(11))


@pytest.mark.parametrize("problem", [ZDT1Config(n_var=8), ZDT3Config(n_var=8), ZDT4Config(n_var=5)])
def test_executes_bi_objective_problems(
    executor: RunExecutor, problem: ZDT1Config | ZDT3Config | ZDT4Config
) -> None:
    config = ExperimentConfig(
        name="t", problem=problem, algorithm=NSGA2Config(pop_size=20), n_gen=5
    )
    sink = ListSink()
    outcome = executor.execute(
        config, seed=1, metrics_sink=sink, progress=ListReporter(), snapshot_dir=None
    )
    assert outcome.generations == 5
    assert set(sink.rows[-1].values) == {"igd", "igd_plus", "hv"}
    assert all(value >= 0 for value in sink.rows[-1].values.values())


def test_cancellation_stops_early(executor: RunExecutor) -> None:
    config = ExperimentConfig(name="t", algorithm=NSGA2Config(pop_size=12), n_gen=1000)
    sink = ListSink()
    calls = iter(range(10_000))
    outcome = executor.execute(
        config,
        seed=1,
        metrics_sink=sink,
        progress=ListReporter(),
        snapshot_dir=None,
        should_cancel=lambda: next(calls) >= 5,
    )
    assert outcome.cancelled
    assert outcome.generations == 5
    assert sink.rows[-1].generation == 5
