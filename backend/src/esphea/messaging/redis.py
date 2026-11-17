"""Redis-backed implementations of the messaging ports."""

import contextlib
import json
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import datetime
from typing import Any

from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from rq import Queue, Worker
from rq.exceptions import InvalidJobOperation, NoSuchJobError
from rq.job import Job
from rq.worker import BaseWorker

from esphea.messaging.events import experiment_channel
from esphea.messaging.ports import (
    JobKind,
    JobRef,
    QueueState,
    RecoveryRecord,
    WatchdogState,
    WorkerState,
)

CANCEL_FLAG_TTL_SECONDS = 7 * 24 * 3600
TASKS: dict[JobKind, str] = {
    JobKind.RUN: "esphea.worker.tasks.execute_run",
    JobKind.ANALYSIS: "esphea.worker.tasks.execute_analysis",
}


PENDING_JOB_STATUSES = frozenset({"queued", "started", "deferred", "scheduled"})
WATCHDOG_KEY = "esphea:watchdog"
RECOVERIES_KEY = "esphea:watchdog:recoveries"
MAX_RECOVERIES = 50


def _job_id(job: JobRef) -> str:
    return f"{job.kind}-{job.entity_id}-{job.attempt}"


def parse_job_id(job_id: str) -> JobRef | None:
    """Inverse of the queue job ids (``None`` for a job that is not ours)."""
    kind, _, rest = job_id.partition("-")
    entity_id, _, attempt = rest.rpartition("-")
    try:
        return JobRef(JobKind(kind), uuid.UUID(entity_id), int(attempt))
    except ValueError:
        return None


def _text(value: bytes | str) -> str:
    return value.decode() if isinstance(value, bytes) else value


class RedisEventPublisher:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def publish(self, experiment_id: uuid.UUID, event: dict[str, Any]) -> None:
        self._redis.publish(experiment_channel(experiment_id), json.dumps(event))


class RedisEventSubscriber:
    def __init__(self, redis: AsyncRedis) -> None:
        self._redis = redis

    async def subscribe(self, experiment_id: uuid.UUID) -> AsyncIterator[str]:
        channel = experiment_channel(experiment_id)
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = message["data"]
                    yield data.decode() if isinstance(data, bytes) else str(data)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()  # type: ignore[no-untyped-call]


class RedisCancellationFlags:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    @staticmethod
    def _key(run_id: uuid.UUID) -> str:
        return f"esphea:cancel:{run_id}"

    def request(self, run_id: uuid.UUID) -> None:
        self._redis.set(self._key(run_id), "1", ex=CANCEL_FLAG_TTL_SECONDS)

    def is_requested(self, run_id: uuid.UUID) -> bool:
        return bool(self._redis.exists(self._key(run_id)))

    def clear(self, run_id: uuid.UUID) -> None:
        self._redis.delete(self._key(run_id))


class RqJobQueue:
    def __init__(self, redis: Redis, *, queue_name: str, job_timeout: int) -> None:
        self._redis = redis
        self._queue = Queue(queue_name, connection=redis)
        self._job_timeout = job_timeout

    def enqueue(self, job: JobRef) -> None:
        self._queue.enqueue(
            TASKS[job.kind],
            str(job.entity_id),
            job.attempt,
            job_id=_job_id(job),
            job_timeout=self._job_timeout,
            result_ttl=3600,
            failure_ttl=7 * 24 * 3600,
        )

    def cancel(self, job: JobRef) -> None:
        with contextlib.suppress(NoSuchJobError, InvalidJobOperation):
            Job.fetch(_job_id(job), connection=self._redis).cancel()

    def is_enqueued(self, job: JobRef) -> bool:
        try:
            queued = Job.fetch(_job_id(job), connection=self._redis)
        except NoSuchJobError:
            return False
        return queued.get_status().value in PENDING_JOB_STATUSES


class RedisActivityMonitor:
    """Reads the RQ registries of the queue and the watchdog's reports."""

    def __init__(self, redis: Redis, *, queue_name: str) -> None:
        self._redis = redis
        self._queue_name = queue_name

    def queue(self) -> QueueState:
        queue = Queue(self._queue_name, connection=self._redis)
        waiting = [parse_job_id(job_id) for job_id in queue.get_job_ids()]
        return QueueState(
            name=self._queue_name,
            waiting=tuple(ref for ref in waiting if ref is not None),
            started=queue.started_job_registry.count,
            failed=queue.failed_job_registry.count,
            finished=queue.finished_job_registry.count,
            deferred=queue.deferred_job_registry.count,
            scheduled=queue.scheduled_job_registry.count,
            workers=tuple(
                sorted(
                    (self._worker(worker) for worker in Worker.all(queue=queue)),
                    key=lambda worker: worker.name,
                )
            ),
        )

    @staticmethod
    def _worker(worker: BaseWorker) -> WorkerState:
        job_id = worker.get_current_job_id()
        state = worker.get_state()
        return WorkerState(
            name=worker.name,
            state=state if state and state != "?" else "unknown",
            hostname=worker.hostname,
            pid=worker.pid,
            job=None if job_id is None else parse_job_id(job_id),
            born_at=worker.birth_date,
            seen_at=worker.last_heartbeat,
            successful_jobs=worker.successful_job_count,
            failed_jobs=worker.failed_job_count,
            working_seconds=worker.total_working_time,
        )

    def watchdog(self) -> WatchdogState | None:
        report = {_text(k): _text(v) for k, v in self._redis.hgetall(WATCHDOG_KEY).items()}
        if "swept_at" not in report:
            return None
        records = [json.loads(raw) for raw in self._redis.lrange(RECOVERIES_KEY, 0, -1)]
        return WatchdogState(
            swept_at=datetime.fromisoformat(report["swept_at"]),
            interval_seconds=float(report["interval"]),
            recoveries=tuple(
                RecoveryRecord(
                    at=datetime.fromisoformat(record["at"]),
                    job=JobRef(JobKind(record["kind"]), uuid.UUID(record["id"]), record["attempt"]),
                    action=record["action"],
                )
                for record in records
            ),
        )


class RedisWatchdogReporter:
    """Lets the watchdog tell when it last swept and what it repaired (last 50)."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    def report_sweep(
        self, at: datetime, interval_seconds: float, recoveries: Sequence[RecoveryRecord]
    ) -> None:
        pipeline = self._redis.pipeline()
        pipeline.hset(
            WATCHDOG_KEY, mapping={"swept_at": at.isoformat(), "interval": interval_seconds}
        )
        for record in recoveries:
            pipeline.lpush(
                RECOVERIES_KEY,
                json.dumps(
                    {
                        "at": record.at.isoformat(),
                        "kind": record.job.kind.value,
                        "id": str(record.job.entity_id),
                        "attempt": record.job.attempt,
                        "action": record.action,
                    }
                ),
            )
        pipeline.ltrim(RECOVERIES_KEY, 0, MAX_RECOVERIES - 1)
        pipeline.execute()
