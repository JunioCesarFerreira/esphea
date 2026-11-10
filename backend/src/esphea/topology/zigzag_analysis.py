"""Zigzag analysis of a run at several fixed scales, with the niche trackers beside it."""

from collections.abc import Callable

from esphea.experiments.storage import SnapshotReader
from esphea.topology.clouds import Normalizer
from esphea.topology.config import ZigzagAnalysisConfig
from esphea.topology.trackers import track_niches
from esphea.topology.zigzag import ZigzagSequence, compute_zigzag
from esphea.topology.zigzag_storage import ZigzagResultWriter

MAX_SIMPLICES = 3_000_000
"""Simplices allowed per scale (about 1 GB of peak memory in our measurements)."""


class ZigzagAnalyzer:
    def __init__(
        self,
        config: ZigzagAnalysisConfig,
        *,
        normalizer: Normalizer,
        max_simplices: int = MAX_SIMPLICES,
    ) -> None:
        self._config = config
        self._normalizer = normalizer
        self._max_simplices = max_simplices

    def analyze(
        self,
        reader: SnapshotReader,
        writer: ZigzagResultWriter,
        *,
        progress: Callable[[int, int], None] = lambda done, total: None,
        should_stop: Callable[[], bool] = lambda: False,
    ) -> None:
        sequence = ZigzagSequence.from_snapshots(reader, self._normalizer)
        writer.write_sequence(sequence)
        total = len(self._config.epsilons)
        progress(0, total)
        for index, epsilon in enumerate(self._config.epsilons):
            result = compute_zigzag(
                sequence,
                epsilon,
                self._config.max_dimension,
                max_simplices=self._max_simplices,
                middle=self._config.middle,
                representatives=self._config.representatives,
                should_stop=should_stop,
            )
            writer.add_result(index, result)
            trackers = track_niches(
                sequence, epsilon, middle=self._config.middle, should_stop=should_stop
            )
            writer.add_trackers(index, trackers)
            progress(index + 1, total)
        writer.close()
