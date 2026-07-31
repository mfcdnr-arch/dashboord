"""Модуль «Обслуживание» (HTTP, admin): статус/ручной запуск свежести и ретенции.

Автоматически это делает планировщик (arq cron). Здесь — предпросмотр объёма
ретенции и ручной запуск (например, перед первым включением окна хранения).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status as http_status

from ... import db
from ..auth.deps import require_roles
from . import backup_service as backup_svc
from . import service

router = APIRouter(prefix="/maintenance", tags=["maintenance"])
admin = require_roles("admin", "superadmin")


@router.get("/retention/preview")
async def retention_preview(months: Optional[int] = Query(None, ge=1), user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        return await service.retention_preview(conn, user["organization_id"], months)


@router.post("/retention/run")
async def retention_run(months: Optional[int] = Query(None, ge=1), user: dict = Depends(admin)):
    async with db.acquire(user["id"]) as conn:
        async with conn.transaction():
            return await service.run_retention(conn, user["organization_id"], months)


@router.post("/freshness/check")
async def freshness_check(stale_days: Optional[int] = Query(None, ge=1), user: dict = Depends(admin)):
    async with db.acquire(user["id"]) as conn:
        async with conn.transaction():
            return await service.check_freshness(conn, user["organization_id"], stale_days)


@router.post("/heal")
async def heal(user: dict = Depends(admin)):
    """Автопочинка прод-стека на уровне приложения (безопасные идемпотентные
    восстановления: бакет MinIO, связь с Redis). admin/superadmin. Событие
    фиксируется в истории (system_heal_log) и в журнале аудита."""
    async with db.acquire(user["id"]) as conn:
        async with conn.transaction():
            return await service.heal_and_log(
                conn, "manual", user_id=user["id"], user_org_id=user["organization_id"])


@router.get("/heal-history")
async def heal_history(limit: int = Query(20, ge=1, le=100), user: dict = Depends(admin)):
    """Последние heal-события (ручные и автоматические от сторожевого arq-cron)."""
    async with db.get_pool().acquire() as conn:
        return await service.heal_history(conn, limit)


@router.get("/backup/status")
async def backup_status(user: dict = Depends(admin)):
    """Статус резервного копирования: что реально лежит на общем томе backups/
    (бэкап делает backup.sh на ХОСТЕ, не приложение) + статус ручного запроса."""
    return backup_svc.get_status()


@router.post("/backup/run-now")
async def backup_run_now(user: dict = Depends(admin)):
    """Запросить внеочередной бэкап: кладёт файл-триггер, который подхватывает
    хостовой наблюдатель ops-trigger-watch.sh (см. backup-schedule.sh)."""
    if backup_svc.is_pending():
        raise HTTPException(http_status.HTTP_409_CONFLICT, "Запрос на бэкап уже ожидает обработки хостом.")
    backup_svc.request_now(user["login"])
    return {"requested": True}


@router.post("/archive/run-now")
async def archive_run_now(user: dict = Depends(admin)):
    """Ежемесячный автоархив дашбордов — вручную, не дожидаясь 1-го числа 02:00.
    Идемпотентно (повторный запуск в том же месяце не дублирует)."""
    from ..dashboards import _archive
    async with db.acquire(user["id"]) as conn:
        async with conn.transaction():
            n = await _archive.run_monthly_auto_archive(conn, user["organization_id"])
    return {"archived": n}


@router.get("/archive/status")
async def archive_status(user: dict = Depends(admin)):
    """Когда последний раз выполнялся автоархив и сколько слепков создано."""
    async with db.get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "select max(archived_at) as last_run, count(*) filter (where archived_at > now() - interval '31 days') as recent "
            "from dashboard_archive where organization_id=$1 and auto", user["organization_id"])
    return {"last_run": row["last_run"].isoformat() if row["last_run"] else None, "recent_count": row["recent"]}
