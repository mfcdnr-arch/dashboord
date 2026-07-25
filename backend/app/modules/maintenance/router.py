"""Модуль «Обслуживание» (HTTP, admin): статус/ручной запуск свежести и ретенции.

Автоматически это делает планировщик (arq cron). Здесь — предпросмотр объёма
ретенции и ручной запуск (например, перед первым включением окна хранения).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from ... import db
from ..auth.deps import require_roles
from . import service

router = APIRouter(prefix="/maintenance", tags=["maintenance"])
admin = require_roles("admin")


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
