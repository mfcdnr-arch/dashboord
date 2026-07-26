"""Фоновый воркер извлечения (arq).

Запуск (локально):
    cd backend && source .venv/bin/activate
    POSTGRES_HOST=localhost POSTGRES_PORT=55432 \
    MINIO_ENDPOINT=localhost:9800 REDIS_HOST=localhost REDIS_PORT=6380 \
    arq app.modules.ingestion.worker.WorkerSettings

Запуск в Docker: отдельный сервис `worker` (см. docker-compose.yml).
"""
from __future__ import annotations

from arq import cron

from ... import db
from ..maintenance import service as maint
from .queue import redis_settings
from .service import run_extraction


async def extract_document(ctx, job_id: str) -> None:
    """Задача arq: полный прогон извлечения по id задания."""
    await run_extraction(job_id)


async def _for_each_org(fn) -> None:
    async with db.get_pool().acquire() as conn:
        orgs = await conn.fetch("select id from organizations")
        for o in orgs:
            async with conn.transaction():
                await fn(conn, o["id"])


async def daily_freshness(ctx) -> None:
    """Планировщик: ежедневная проверка свежести данных → уведомления."""
    await _for_each_org(maint.check_freshness)


async def weekly_retention(ctx) -> None:
    """Планировщик: еженедельная ретенция (скользящее окно хранения)."""
    await _for_each_org(maint.run_retention)


async def on_startup(ctx) -> None:
    await db.connect()


async def on_shutdown(ctx) -> None:
    await db.disconnect()


class WorkerSettings:
    functions = [extract_document]
    cron_jobs = [
        cron(daily_freshness, hour=7, minute=0),                 # ежедневно 07:00 — свежесть
        cron(weekly_retention, weekday="sun", hour=3, minute=0),  # вс 03:00 — ретенция
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = redis_settings()
    # Живость воркера: раз в 60с пишет health-ключ в Redis; healthcheck контейнера
    # проверяет его командой `arq --check` (см. docker-compose.prod.yml).
    health_check_interval = 60
    max_jobs = 4  # один сервер, ~20 пользователей — умеренный параллелизм
