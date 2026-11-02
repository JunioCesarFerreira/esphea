"""Redis-backed implementations of the messaging ports."""

import contextlib
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from rq import Queue
from rq.exceptions import InvalidJobOperation, NoSuchJobError
from rq.job import Job

from esphea.messaging.events import experiment_channel

CANCEL_FLAG_TTL_SECONDS = 7 * 24 * 3600
RUN_TASK = "esphea.worker.tasks.execute_run"


def _job_id(run_id: uuid.UUID) -> str:
    return f"run-{run_id}"


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

    def enqueue_run(self, run_id: uuid.UUID) -> None:
        self._queue.enqueue(
            RUN_TASK,
            str(run_id),
            job_id=_job_id(run_id),
            job_timeout=self._job_timeout,
            result_ttl=3600,
            failure_ttl=7 * 24 * 3600,
        )

    def cancel_run(self, run_id: uuid.UUID) -> None:
        with contextlib.suppress(NoSuchJobError, InvalidJobOperation):
            Job.fetch(_job_id(run_id), connection=self._redis).cancel()
