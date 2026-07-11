"""Пул подключений к PostgreSQL (asyncpg)."""
from __future__ import annotations

import asyncpg

from .config import settings

_pool: asyncpg.Pool | None = None


async def connect() -> None:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.database_dsn, min_size=1, max_size=10
        )


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Пул БД не инициализирован")
    return _pool


async def check_db() -> bool:
    """Проверка живости БД для /health."""
    async with get_pool().acquire() as conn:
        return await conn.fetchval("select 1") == 1
