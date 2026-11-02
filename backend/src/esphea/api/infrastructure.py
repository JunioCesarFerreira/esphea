"""Composition root of the API: wires ports to their Redis/Postgres implementations."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from sqlalchemy.orm import Session, sessionmaker

from esphea.experiments.registry import ProblemRegistry, default_problem_registry
from esphea.messaging.ports import CancellationFlags, EventPublisher, EventSubscriber, JobQueue
from esphea.messaging.redis import (
    RedisCancellationFlags,
    RedisEventPublisher,
    RedisEventSubscriber,
    RqJobQueue,
)
from esphea.persistence.db import create_db_engine, create_session_factory
from esphea.settings import Settings


async def _nothing() -> None:
    return None


@dataclass
class Infrastructure:
    sessions: sessionmaker[Session]
    queue: JobQueue
    cancellation: CancellationFlags
    publisher: EventPublisher
    subscriber: EventSubscriber
    problems: ProblemRegistry
    runs_dir: Path
    close: Callable[[], Awaitable[None]] = _nothing


def build_infrastructure(settings: Settings) -> Infrastructure:
    engine = create_db_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    async_redis = AsyncRedis.from_url(settings.redis_url, decode_responses=True)

    async def close() -> None:
        await async_redis.aclose()
        redis.close()
        engine.dispose()

    return Infrastructure(
        sessions=create_session_factory(engine),
        queue=RqJobQueue(
            redis, queue_name=settings.queue_name, job_timeout=settings.job_timeout_seconds
        ),
        cancellation=RedisCancellationFlags(redis),
        publisher=RedisEventPublisher(redis),
        subscriber=RedisEventSubscriber(async_redis),
        problems=default_problem_registry(),
        runs_dir=settings.runs_dir,
        close=close,
    )
