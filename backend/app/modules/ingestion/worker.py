"""Фоновый воркер извлечения (arq).

Запуск (локально):
    cd backend && source .venv/bin/activate
    POSTGRES_HOST=localhost POSTGRES_PORT=55432 \
    MINIO_ENDPOINT=localhost:9800 REDIS_HOST=localhost REDIS_PORT=6380 \
    arq app.modules.ingestion.worker.WorkerSettings

Запуск в Docker: отдельный сервис `worker` (см. docker-compose.yml).
"""
from __future__ import annotations

from ... import db
from .queue import redis_settings
from .service import run_extraction


async def extract_document(ctx, job_id: str) -> None:
    """Задача arq: полный прогон извлечения по id задания."""
    await run_extraction(job_id)


async def on_startup(ctx) -> None:
    await db.connect()


async def on_shutdown(ctx) -> None:
    await db.disconnect()


class WorkerSettings:
    functions = [extract_document]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = redis_settings()
    max_jobs = 4  # один сервер, ~20 пользователей — умеренный параллелизм
