"""Сервис обслуживания данных: проверка свежести + ретенция (скользящее окно).

- check_freshness: по каждому объекту смотрит дату последней загрузки; если
  данные не поступали дольше stale_days — создаёт уведомление (антидубль 7 дней).
- retention_preview / run_retention: считает/удаляет релизы датасетов старше окна
  (reporting_period_start < сегодня − N месяцев). Каскад чистит values/поля/связи.
"""
from __future__ import annotations

import asyncio
import time

from ...config import settings
from ..documents import storage
from ..notifications import service as notif


async def heal() -> dict:
    """Автопочинка прод-стека на уровне приложения: безопасные идемпотентные
    восстановления. Инфраструктурный авто-рестарт упавших контейнеров делает сам
    Docker (restart: unless-stopped в compose) — здесь то, что чинит приложение.

    Действия: (1) создать бакет MinIO, если пропал (частая проблема после сброса
    тома); (2) проверить доступность Redis. Возвращает список действий с итогом."""
    actions = []

    # (1) MinIO: гарантировать наличие бакета (idempotent — создаёт, если нет).
    # Синхронный minio-клиент — в отдельном потоке, чтобы не блокировать event-loop.
    def _ensure_bucket() -> bool:
        client = storage.get_client()
        was = client.bucket_exists(settings.minio_bucket)
        if not was:
            storage.ensure_bucket()
        return was

    t0 = time.perf_counter()
    try:
        existed = await asyncio.to_thread(_ensure_bucket)
        actions.append({
            "name": "MinIO: бакет документов",
            "ok": True,
            "result": "уже был" if existed else "создан заново",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        })
    except Exception as e:
        actions.append({"name": "MinIO: бакет документов", "ok": False, "result": f"ошибка: {e}"})

    # (2) Redis: проверить связь (перезапуск сервиса — задача Docker, не приложения).
    t0 = time.perf_counter()
    try:
        import redis.asyncio as aioredis
        r = aioredis.Redis(host=settings.redis_host, port=settings.redis_port, socket_connect_timeout=2)
        ok = bool(await r.ping())
        await r.aclose()
        actions.append({
            "name": "Redis: связь",
            "ok": ok,
            "result": "доступен" if ok else "недоступен — проверьте контейнер",
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
        })
    except Exception as e:
        actions.append({"name": "Redis: связь", "ok": False, "result": f"недоступен: {e}"})

    return {"actions": actions, "healthy": all(a["ok"] for a in actions)}


async def check_freshness(conn, org_id, stale_days: int | None = None) -> dict:
    """Создаёт уведомления по объектам с устаревшими данными. Возвращает сводку."""
    days = stale_days if stale_days is not None else settings.stale_days
    rows = await conn.fetch(
        "select o.id, o.name, max(r.created_at) as last_upload, "
        "max(r.reporting_period_start) as last_period, count(r.id) as releases "
        "from objects o left join dataset_releases r on r.object_id=o.id "
        "where o.organization_id=$1 group by o.id, o.name", org_id)
    recipients = await notif.management_user_ids(conn, org_id)
    created, stale = 0, []
    for o in rows:
        if o["releases"] == 0 or o["last_upload"] is None:
            continue  # новые объекты без данных не считаем «устаревшими»
        age_days = (await conn.fetchval("select extract(day from now() - $1)", o["last_upload"]))
        if age_days is None or age_days < days:
            continue
        stale.append({"object": o["name"], "days": int(age_days)})
        if await notif.recent_event_exists(conn, org_id, "data.stale", str(o["id"]), 7):
            continue  # уже уведомляли недавно
        await notif.notify(
            conn, org_id, "data.stale", "object", str(o["id"]),
            {"object_name": o["name"], "days_since_upload": int(age_days),
             "last_period": o["last_period"].isoformat() if o["last_period"] else None,
             "threshold_days": days},
            recipients)
        created += 1
    return {"stale_objects": stale, "notifications_created": created}


async def retention_preview(conn, org_id, months: int | None = None) -> dict:
    """Сколько релизов/значений будет удалено при ретенции (без удаления)."""
    m = months if months is not None else settings.retention_months
    if not m or m <= 0:
        return {"enabled": False, "months": m, "releases": 0, "values": 0}
    rel = await conn.fetchval(
        "select count(*) from dataset_releases where organization_id=$1 "
        "and reporting_period_start < (current_date - make_interval(months => $2))", org_id, m)
    val = await conn.fetchval(
        "select count(*) from dataset_values v join dataset_releases r on r.id=v.dataset_release_id "
        "where r.organization_id=$1 and r.reporting_period_start < (current_date - make_interval(months => $2))",
        org_id, m)
    return {"enabled": True, "months": m, "releases": rel, "values": val}


async def run_retention(conn, org_id, months: int | None = None, notify_admins: bool = True) -> dict:
    """Удаляет релизы датасетов старше окна (каскадом — значения/поля/связи)."""
    m = months if months is not None else settings.retention_months
    if not m or m <= 0:
        return {"enabled": False, "deleted_releases": 0}
    res = await conn.execute(
        "delete from dataset_releases where organization_id=$1 "
        "and reporting_period_start < (current_date - make_interval(months => $2))", org_id, m)
    deleted = int(res.rsplit(" ", 1)[-1]) if res.startswith("DELETE") else 0
    if deleted and notify_admins:
        recipients = await notif.management_user_ids(conn, org_id)
        await notif.notify(
            conn, org_id, "data.retention", "organization", str(org_id),
            {"deleted_releases": deleted, "window_months": m}, recipients)
    return {"enabled": True, "months": m, "deleted_releases": deleted}
