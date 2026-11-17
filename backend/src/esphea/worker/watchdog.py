"""Watchdog process: ``python -m esphea.worker.watchdog``."""

import logging
import signal
import threading
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from types import FrameType

from redis import Redis

from esphea.messaging.ports import JobRef, RecoveryRecord
from esphea.messaging.redis import RedisEventPublisher, RedisWatchdogReporter, RqJobQueue
from esphea.persistence.db import create_db_engine, create_session_factory
from esphea.services.watchdog import AnalysisJobs, Recovery, RunJobs, Watchdog
from esphea.settings import get_settings

logger = logging.getLogger("esphea.watchdog")


def _records(at: datetime, recoveries: Sequence[Recovery]) -> list[RecoveryRecord]:
    return [
        RecoveryRecord(
            at=at,
            job=JobRef(recovery.kind, uuid.UUID(recovery.job_id), recovery.attempt),
            action=recovery.action.value,
        )
        for recovery in recoveries
    ]


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    watchdog = Watchdog(
        create_session_factory(engine),
        queue=RqJobQueue(
            redis, queue_name=settings.queue_name, job_timeout=settings.job_timeout_seconds
        ),
        jobs=[
            RunJobs(runs_dir=settings.runs_dir, publisher=RedisEventPublisher(redis)),
            AnalysisJobs(runs_dir=settings.runs_dir),
        ],
        lease_timeout=timedelta(seconds=settings.lease_timeout_seconds),
        max_attempts=settings.max_run_attempts,
        enqueue_grace=timedelta(seconds=settings.enqueue_grace_seconds),
    )
    # Shown on the Activity page: when the watchdog last swept, and what it repaired.
    reporter = RedisWatchdogReporter(redis)

    stop = threading.Event()

    def request_stop(signum: int, _: FrameType | None) -> None:
        logger.info("received signal %d; stopping", signum)
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    logger.info(
        "watching runs and analyses every %.0fs (lease timeout %.0fs, up to %d attempts)",
        settings.watchdog_interval_seconds,
        settings.lease_timeout_seconds,
        settings.max_run_attempts,
    )
    try:
        while not stop.is_set():
            try:
                recoveries = watchdog.sweep()
            except Exception:  # transient database/Redis errors: try again next tick
                logger.exception("sweep failed")
            else:
                now = datetime.now(UTC)
                try:
                    reporter.report_sweep(
                        now, settings.watchdog_interval_seconds, _records(now, recoveries)
                    )
                except Exception:
                    logger.warning("could not report the sweep", exc_info=True)
            stop.wait(settings.watchdog_interval_seconds)
    finally:
        redis.close()
        engine.dispose()


if __name__ == "__main__":
    main()
