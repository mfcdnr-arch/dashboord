"""Сервис отчётов.

Системный мониторинг (Q5): CPU/RAM/диск через psutil + статусы сервисов
(PostgreSQL/Redis/MinIO) + размер БД, с уровнями-порогами (good/warn/danger).
Посещаемость: агрегаты по login_events (входы/неудачи/активные, по дням, топ).
Сбор локальный, on-prem, без внешних SaaS.
"""
from __future__ import annotations

import time

import psutil

from ...config import settings
from ..documents import storage


def _level(pct: float, warn: float, crit: float) -> str:
    return "danger" if pct >= crit else ("warn" if pct >= warn else "good")


async def system_health(conn) -> dict:
    cpu = psutil.cpu_percent(interval=0.3)
    vm = psutil.virtual_memory()
    du = psutil.disk_usage("/")
    try:
        load = list(psutil.getloadavg())
    except (AttributeError, OSError):
        load = None
    uptime_sec = int(time.time() - psutil.boot_time())

    services = []
    try:
        pg_ok = (await conn.fetchval("select 1")) == 1
    except Exception:
        pg_ok = False
    db_size = None
    if pg_ok:
        try:
            db_size = await conn.fetchval("select pg_database_size(current_database())")
        except Exception:
            db_size = None
    services.append({"name": "PostgreSQL", "ok": pg_ok})

    redis_ok = False
    try:
        import redis.asyncio as aioredis
        r = aioredis.Redis(host=settings.redis_host, port=settings.redis_port, socket_connect_timeout=1)
        redis_ok = bool(await r.ping())
        await r.aclose()
    except Exception:
        redis_ok = False
    services.append({"name": "Redis", "ok": redis_ok})

    minio_ok = False
    try:
        minio_ok = bool(storage.get_client().bucket_exists(settings.minio_bucket))
    except Exception:
        minio_ok = False
    services.append({"name": "MinIO", "ok": minio_ok})

    return {
        "cpu": {"percent": round(cpu, 1), "level": _level(cpu, 70, 90)},
        "memory": {"percent": round(vm.percent, 1), "used": vm.used, "total": vm.total, "level": _level(vm.percent, 80, 92)},
        "disk": {"percent": round(du.percent, 1), "used": du.used, "total": du.total, "level": _level(du.percent, 80, 92)},
        "load": load, "cores": psutil.cpu_count(), "uptime_sec": uptime_sec,
        "db_size": db_size, "services": services,
    }


async def attendance(conn, org_id) -> dict:
    totals = await conn.fetchrow(
        "select count(*) filter (where success) as logins, "
        "count(*) filter (where not success) as failed, "
        "count(distinct user_id) filter (where success) as active_users "
        "from login_events where organization_id=$1 and created_at >= now() - interval '30 days'", org_id)
    per_day = await conn.fetch(
        "select date_trunc('day', created_at)::date as day, "
        "count(*) filter (where success) as logins, count(*) filter (where not success) as failed "
        "from login_events where organization_id=$1 and created_at >= now() - interval '14 days' "
        "group by 1 order by 1", org_id)
    top = await conn.fetch(
        "select u.login, count(*) as logins from login_events e join users u on u.id=e.user_id "
        "where e.organization_id=$1 and e.success and e.created_at >= now() - interval '30 days' "
        "group by u.login order by count(*) desc limit 5", org_id)
    return {
        "totals": {"logins": totals["logins"], "failed": totals["failed"], "active_users": totals["active_users"]},
        "per_day": [{"day": r["day"].isoformat(), "logins": r["logins"], "failed": r["failed"]} for r in per_day],
        "top_users": [{"login": r["login"], "logins": r["logins"]} for r in top],
    }
