"""RQ entry points. RQ forks a fresh process per job, so dependencies are built per call."""

import logging
import uuid

from redis import Redis

from esphea.experiments.registry import default_algorithm_registry, default_problem_registry
from esphea.experiments.runner import RunExecutor
from esphea.messaging.redis import RedisCancellationFlags, RedisEventPublisher
from esphea.persistence.db import create_db_engine, create_session_factory
from esphea.services.execution import RunService
from esphea.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def execute_run(run_id: str) -> str | None:
    settings = get_settings()
    engine = create_db_engine(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    try:
        service = RunService(
            create_session_factory(engine),
            executor=RunExecutor(default_problem_registry(), default_algorithm_registry()),
            publisher=RedisEventPublisher(redis),
            cancellation=RedisCancellationFlags(redis),
            runs_dir=settings.runs_dir,
        )
        status = service.execute(uuid.UUID(run_id))
        return None if status is None else status.value
    finally:
        redis.close()
        engine.dispose()
