"""Очередь заданий извлечения на Redis (arq).

Пул создаётся один раз при старте приложения (lifespan) и переиспользуется
для постановки задач. Сам воркер — в worker.py (отдельный процесс).
"""
from __future__ import annotations

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from ...config import settings

_redis: ArqRedis | None = None


def redis_settings() -> RedisSettings:
    return RedisSettings(host=settings.redis_host, port=settings.redis_port)


async def connect() -> None:
    global _redis
    if _redis is None:
        _redis = await create_pool(redis_settings())


async def disconnect() -> None:
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None


async def enqueue_extraction(job_id: str) -> None:
    """Ставит задачу извлечения в очередь воркера."""
    if _redis is None:
        raise RuntimeError("Пул Redis не инициализирован")
    await _redis.enqueue_job("extract_document", job_id)
