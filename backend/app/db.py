"""Пул подключений к PostgreSQL (asyncpg)."""
from __future__ import annotations

import contextvars
from contextlib import asynccontextmanager

import asyncpg

from .config import settings

_pool: asyncpg.Pool | None = None

# IP текущего запроса. Ставит ASGI-middleware (capture_client_ip в main.py),
# читает acquire() — чтобы триггеры аудита и write_event писали ip_address.
current_ip: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_ip", default=None)


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


@asynccontextmanager
async def acquire(actor_user_id: str | None = None):
    """Соединение из пула с проставленным автором действий.

    Триггеры аудита (fn_audit_generic) читают `app.current_user_id`, чтобы
    записать actor_user_id в audit_log. Проставляем GUC на сессию сразу после
    захвата соединения; пустая строка (нет актора) в триггере даёт NULL.
    asyncpg при возврате соединения в пул делает RESET ALL, но мы всё равно
    переустанавливаем значение при каждом захвате — автор не «протечёт» между
    запросами на переиспользуемом соединении. Заодно проставляем app.client_ip
    (IP текущего запроса из contextvar) — его пишут триггеры аудита и write_event.
    """
    async with get_pool().acquire() as conn:
        await conn.execute(
            "select set_config('app.current_user_id', $1, false), "
            "set_config('app.client_ip', $2, false)",
            str(actor_user_id) if actor_user_id else "",
            current_ip.get() or "",
        )
        yield conn


async def check_db() -> bool:
    """Проверка живости БД для /health."""
    async with get_pool().acquire() as conn:
        return await conn.fetchval("select 1") == 1
