"""Фоновый воркер извлечения (arq).

Запуск (локально):
    cd backend && source .venv/bin/activate
    POSTGRES_HOST=localhost POSTGRES_PORT=55432 \
    MINIO_ENDPOINT=localhost:9800 REDIS_HOST=localhost REDIS_PORT=6380 \
    arq app.modules.ingestion.worker.WorkerSettings

Запуск в Docker: отдельный сервис `worker` (см. docker-compose.yml).
"""
from __future__ import annotations

import logging

from arq import cron

from ... import db
from ..maintenance import service as maint
from ..reports import service as reports_svc
from . import queue, service
from .queue import redis_settings
from .service import run_extraction

log = logging.getLogger(__name__)


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


async def monthly_auto_archive(ctx) -> None:
    """Планировщик: 1-го числа — слепки дашбордов с флажком auto_archive
    за прошедший месяц (идемпотентно: повторный запуск не дублирует)."""
    from ..dashboards import _archive
    await _for_each_org(_archive.run_monthly_auto_archive)


async def pickup_pending(ctx) -> None:
    """Добор файлов, которые не дошли до распознавания.

    Загрузка ставит задание сама, но очередь могла быть недоступна, воркер —
    перезапущен на середине, а файлы старых загрузок вообще заливались без
    задания. Без добора такой файл лежит в папке молча и навсегда: человек
    видит его в списке и уверен, что система им занимается.

    Берём версии документов, у которых нет ни одного успешного или живого
    задания и с загрузки прошло больше 10 минут (чтобы не гнаться за тем, что
    прямо сейчас в работе). Потолок за прогон — 50 файлов: разбор тяжёлый, а
    хвост доберётся следующим запуском.
    """
    async with db.get_pool().acquire() as conn:
        rows = await conn.fetch(
            "select dv.id from document_versions dv "
            "where dv.created_at < now() - interval '10 minutes' "
            "  and not exists (select 1 from extraction_jobs j "
            "                  where j.document_version_id = dv.id "
            "                    and (j.status in ('queued','running','succeeded','needs_review'))) "
            "order by dv.created_at desc limit 50")
        for r in rows:
            job_id = await service.enqueue_or_run(conn, str(r["id"]))
            await queue.enqueue_extraction(job_id)
    if rows:
        log.info("Добор распознавания: поставлено заданий — %s", len(rows))


async def system_watchdog(ctx) -> None:
    """Планировщик: каждые 10 мин — если система в статусе degraded, безопасно
    починить (heal) и залогировать; если после починки всё ещё плохо — уведомить
    admin/moderator каждой организации (антидубль — не чаще раза в час)."""
    async with db.get_pool().acquire() as conn:
        health = await reports_svc.system_health(conn)
        if health["status"] != "degraded":
            return
        result = await maint.heal_and_log(conn, "auto")
        if not result["healthy"]:
            await _for_each_org(lambda c, org_id: maint.notify_degraded(c, org_id, result))


async def on_startup(ctx) -> None:
    await db.connect()


async def on_shutdown(ctx) -> None:
    await db.disconnect()


class WorkerSettings:
    functions = [extract_document]
    cron_jobs = [
        cron(pickup_pending, hour=6, minute=30),                   # ежедневно 06:30 — добор нераспознанных
        cron(daily_freshness, hour=7, minute=0),                 # ежедневно 07:00 — свежесть
        cron(weekly_retention, weekday="sun", hour=3, minute=0),  # вс 03:00 — ретенция
        cron(monthly_auto_archive, day=1, hour=2, minute=0),      # 1-е число 02:00 — автоархив за прошлый месяц
        cron(system_watchdog, minute={0, 10, 20, 30, 40, 50}),    # каждые 10 мин — сторожевая самодиагностика/самопочинка
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    redis_settings = redis_settings()
    # Живость воркера: раз в 60с пишет health-ключ в Redis; healthcheck контейнера
    # проверяет его командой `arq --check` (см. docker-compose.prod.yml).
    health_check_interval = 60
    max_jobs = 4  # один сервер, ~20 пользователей — умеренный параллелизм
