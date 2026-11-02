"""Heartbeat leases that keep a worker's ownership of a job alive."""

import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from esphea.persistence.repositories import LeasedJobRepository

logger = logging.getLogger(__name__)


class LeaseLostError(RuntimeError):
    """The attempt no longer owns its job (it was recovered by the watchdog)."""


def database_renewal(
    sessions: sessionmaker[Session],
    repository: Callable[[Session], LeasedJobRepository[Any]],
    job_id: uuid.UUID,
    attempt: int,
) -> Callable[[], bool]:
    """Renewal function refreshing the heartbeat of ``attempt`` of ``job_id``."""

    def renew() -> bool:
        with sessions.begin() as session:
            return repository(session).renew_lease(job_id, attempt)

    return renew


class Lease:
    """Keeps an attempt's ownership of a job alive with periodic heartbeats.

    A background thread calls ``renew`` every ``interval`` seconds. The lease
    is lost when ``renew`` reports that the attempt no longer owns the job, or
    when no renewal succeeded for ``self_fence_after`` seconds (e.g. the
    database is unreachable). That bound must be shorter than the watchdog's
    lease timeout, so a cut-off worker stops before its job is retried elsewhere.
    """

    def __init__(
        self,
        renew: Callable[[], bool],
        *,
        name: str,
        interval: float,
        self_fence_after: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if self_fence_after <= interval:
            raise ValueError("self_fence_after must exceed the heartbeat interval")
        self._renew = renew
        self._name = name
        self._interval = interval
        self._self_fence_after = self_fence_after
        self._clock = clock
        self._last_renewal = clock()
        self._lost = threading.Event()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def lost(self) -> bool:
        return self._lost.is_set()

    def renew(self) -> bool:
        """Renew once; returns whether the lease is still held."""
        try:
            held = self._renew()
        except Exception:
            logger.warning("heartbeat of %s failed", self._name, exc_info=True)
            held = True  # unknown: rely on the self-fencing deadline below
        else:
            if held:
                self._last_renewal = self._clock()
        if not held or self._clock() - self._last_renewal >= self._self_fence_after:
            self._lost.set()
        return not self.lost

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name=f"lease-{self._name}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._thread is not None:
            self._thread.join()

    def _loop(self) -> None:
        while not self._stopped.wait(self._interval):
            if not self.renew():
                logger.error("%s: lease lost; stopping this attempt", self._name)
                return
