"""Observers that turn a running algorithm into experiment data."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from esphea.core.observer import AlgorithmObserver
from esphea.core.population import Population
from esphea.core.records import GenerationRecord
from esphea.core.types import BoolArray, FloatArray, IntArray
from esphea.experiments.lineage import IdentityTracker
from esphea.experiments.storage import SnapshotWriter
from esphea.metrics import QualityIndicator, non_dominated_mask


def non_dominated_front(population: Population) -> FloatArray:
    """Objective vectors of the first front (uses ``rank`` when available)."""
    if "rank" in population.attributes:
        mask: BoolArray = population.attribute("rank") == 0
    else:
        mask = non_dominated_mask(population.F)
    return population.F[mask]


@dataclass(frozen=True, slots=True)
class GenerationMetrics:
    generation: int
    n_nondominated: int
    elapsed_seconds: float
    values: dict[str, float] = field(default_factory=dict)


class MetricsSink(Protocol):
    def add(self, metrics: GenerationMetrics) -> None: ...

    def flush(self) -> None: ...


class IndicatorObserver(AlgorithmObserver):
    """Computes quality indicators on the first front every ``every`` generations.

    The last and the initial generations are always measured.
    """

    def __init__(
        self,
        indicators: Sequence[QualityIndicator],
        sink: MetricsSink,
        *,
        every: int = 1,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._indicators = tuple(indicators)
        self._sink = sink
        self._every = every
        self._clock = clock
        self._started = clock()
        self._pending: Population | None = None
        self._pending_generation = 0
        self.latest: GenerationMetrics | None = None

    def on_start(self, initial: Population) -> None:
        self._started = self._clock()
        self._measure(0, initial)

    def on_generation(self, record: GenerationRecord) -> None:
        if record.generation % self._every == 0:
            self._measure(record.generation, record.survivors)
            self._pending = None
        else:
            self._pending = record.survivors
            self._pending_generation = record.generation

    def on_finish(self, final: Population, generations: int) -> None:
        if self._pending is not None:
            self._measure(self._pending_generation, self._pending)
        self._sink.flush()

    def _measure(self, generation: int, population: Population) -> None:
        front = non_dominated_front(population)
        metrics = GenerationMetrics(
            generation=generation,
            n_nondominated=int(front.shape[0]),
            elapsed_seconds=self._clock() - self._started,
            values={indicator.name: indicator(front) for indicator in self._indicators},
        )
        self.latest = metrics
        self._sink.add(metrics)


class SnapshotObserver(AlgorithmObserver):
    """Writes generation snapshots; the last generation is always stored.

    Identities are tracked on every generation, stored or not, so stored
    individuals always carry their run-unique ``individual_id``.
    """

    def __init__(self, writer: SnapshotWriter, *, every: int = 1) -> None:
        self._writer = writer
        self._every = every
        self._identities = IdentityTracker()
        self._pending: tuple[GenerationRecord, IntArray, IntArray] | None = None

    def on_start(self, initial: Population) -> None:
        self._writer.write_initial(initial, self._identities.start(initial))

    def on_generation(self, record: GenerationRecord) -> None:
        population_ids, offspring_ids = self._identities.advance(record)
        if record.generation % self._every == 0:
            self._writer.write_generation(record, population_ids, offspring_ids)
            self._pending = None
        else:
            self._pending = (record, population_ids, offspring_ids)

    def on_finish(self, final: Population, generations: int) -> None:
        if self._pending is not None:
            self._writer.write_generation(*self._pending)
        self._writer.close()


@dataclass(frozen=True, slots=True)
class RunProgress:
    generation: int
    n_gen: int
    front: FloatArray
    metrics: GenerationMetrics | None


class ProgressReporter(Protocol):
    def report(self, progress: RunProgress) -> None: ...


class ProgressObserver(AlgorithmObserver):
    """Reports progress at most once per ``min_interval`` seconds (and at the end).

    The reported front is subsampled to ``max_front_points`` to keep messages small.
    """

    def __init__(
        self,
        reporter: ProgressReporter,
        *,
        n_gen: int,
        metrics: IndicatorObserver | None = None,
        min_interval: float = 0.25,
        max_front_points: int = 500,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._reporter = reporter
        self._n_gen = n_gen
        self._metrics = metrics
        self._min_interval = min_interval
        self._max_front_points = max_front_points
        self._clock = clock
        self._last_report = -np.inf

    def on_start(self, initial: Population) -> None:
        self._report(0, initial)

    def on_generation(self, record: GenerationRecord) -> None:
        if self._clock() - self._last_report >= self._min_interval:
            self._report(record.generation, record.survivors)

    def on_finish(self, final: Population, generations: int) -> None:
        self._report(generations, final)

    def _report(self, generation: int, population: Population) -> None:
        front = non_dominated_front(population)
        if front.shape[0] > self._max_front_points:
            step = front.shape[0] / self._max_front_points
            front = front[(np.arange(self._max_front_points) * step).astype(np.intp)]
        self._last_report = self._clock()
        self._reporter.report(
            RunProgress(
                generation=generation,
                n_gen=self._n_gen,
                front=front,
                metrics=self._metrics.latest if self._metrics else None,
            )
        )
