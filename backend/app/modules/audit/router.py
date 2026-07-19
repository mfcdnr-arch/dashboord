"""Модуль «Аудит действий» (HTTP): чтение журнала изменений сущностей.

Журнал — чувствительная информация (кто что менял), поэтому доступ только у
администратора. Наполнение — триггерами БД; здесь только чтение.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ... import db
from ..auth.deps import require_roles
from . import service
from .service import AuditError

router = APIRouter(tags=["audit"])
admin = require_roles("admin")


@router.get("/audit")
async def list_audit(
    user: dict = Depends(admin),
    actor: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    action: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    include_views: bool = False,
    limit: int = Query(50, ge=1, le=service.MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.list_events(
                conn, user["organization_id"], actor=actor, entity_type=entity_type,
                entity_id=entity_id, action=action, date_from=date_from, date_to=date_to,
                include_views=include_views, limit=limit, offset=offset)
        except AuditError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.get("/audit/{event_id}")
async def get_audit(event_id: str, user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.get_event(conn, user["organization_id"], event_id)
        except AuditError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
