"""Модуль «Уведомления» (HTTP): лента текущего пользователя (колокольчик)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ... import db
from ..auth.deps import get_current_user
from . import service

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
async def list_notifications(user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        return await service.list_for_user(conn, user["id"])


@router.post("/notifications/{recipient_id}/read")
async def read_notification(recipient_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        await service.mark_read(conn, user["id"], recipient_id)
        return {"ok": True}


@router.post("/notifications/read-all")
async def read_all(user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        return await service.mark_all_read(conn, user["id"])
