"""Observer interface used to plug analyses into the evolutionary loop."""

from collections.abc import Sequence

from esphea.core.population import Population
from esphea.core.records import GenerationRecord


class AlgorithmObserver:
    """Receives the state of a run as it evolves.

    Methods are no-ops by default, so each observer overrides only the events
    it cares about. Observers must treat what they receive as read-only.
    """

    def on_start(self, initial: Population) -> None:
        """Called once with the evaluated and ranked initial population ``P_0``."""

    def on_generation(self, record: GenerationRecord) -> None:
        """Called after every generation."""

    def on_finish(self, final: Population, generations: int) -> None:
        """Called once when the loop ends (normally or by early termination)."""


class CompositeObserver(AlgorithmObserver):
    """Broadcasts every event to a sequence of observers, in order."""

    def __init__(self, observers: Sequence[AlgorithmObserver]) -> None:
        self._observers = tuple(observers)

    def on_start(self, initial: Population) -> None:
        for observer in self._observers:
            observer.on_start(initial)

    def on_generation(self, record: GenerationRecord) -> None:
        for observer in self._observers:
            observer.on_generation(record)

    def on_finish(self, final: Population, generations: int) -> None:
        for observer in self._observers:
            observer.on_finish(final, generations)
