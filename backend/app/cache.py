"""Небольшой TTL-кэш на Redis для данных виджетов.

Мягкая деградация: любая ошибка Redis → кэш «прозрачен» (get→None, set→no-op),
приложение продолжает работать напрямую из БД. Инвалидация — по TTL и явно
по префиксу при правке виджета.
"""
from __future__ import annotations

import redis.asyncio as aioredis

from .config import settings

# Окно устаревания данных виджета (сек). Данные обновляются при выпуске
# датасета; ~секунды задержки для дашборда допустимы.
WIDGET_DATA_TTL = 30

_redis: aioredis.Redis | None = None


async def connect() -> None:
    global _redis
    if _redis is None:
        _redis = aioredis.Redis(host=settings.redis_host, port=settings.redis_port,
                                decode_responses=True)


async def disconnect() -> None:
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:
            pass
        _redis = None


async def get(key: str) -> str | None:
    if _redis is None:
        return None
    try:
        return await _redis.get(key)
    except Exception:
        return None


async def set(key: str, value: str, ttl: int) -> None:
    if _redis is None:
        return
    try:
        await _redis.set(key, value, ex=ttl)
    except Exception:
        pass


async def delete_prefix(prefix: str) -> None:
    """Удаляет все ключи с данным префиксом (инвалидация кэша виджета)."""
    if _redis is None:
        return
    try:
        async for k in _redis.scan_iter(match=f"{prefix}*"):
            await _redis.delete(k)
    except Exception:
        pass
