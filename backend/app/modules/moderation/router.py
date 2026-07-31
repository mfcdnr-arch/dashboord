"""Модуль «Модерация» (HTTP): очередь, решения, отправка на проверку, история.

Отправить на проверку может автор/модератор; одобрять/возвращать —
модератор/старший модератор/админ. Прямая публикация (override) остаётся
в модуле dashboards и доступна только админу.
"""
from __future__ import annotations

from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ... import db
from ..auth.deps import get_current_user, require_roles
from . import service
from .service import ModerationError

router = APIRouter(tags=["moderation"])
moderator = require_roles("admin", "moderator", "senior_moderator")


def _bad(e: ModerationError) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if "не найден" in str(e) else status.HTTP_400_BAD_REQUEST
    return HTTPException(code, str(e))


class DecideIn(BaseModel):
    decision: str  # 'approve' | 'return'
    reason_code: Optional[str] = None
    comment: Optional[str] = None
    checklist: Optional[Dict[str, str]] = None


@router.get("/moderation/queue")
async def moderation_queue(user: dict = Depends(moderator)):
    async with db.acquire(user["id"]) as conn:
        return await service.queue(conn, user["organization_id"], user)


@router.get("/moderation/reason-codes")
async def moderation_reason_codes(user: dict = Depends(moderator)):
    async with db.acquire(user["id"]) as conn:
        return await service.list_reason_codes(conn)


@router.post("/dashboards/{dashboard_id}/submit-review")
async def submit_review(dashboard_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.submit_for_review(conn, user["organization_id"], user, dashboard_id)
        except ModerationError as e:
            raise _bad(e)


@router.post("/dashboards/{dashboard_id}/cancel-review")
async def cancel_review(dashboard_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.cancel_review(conn, user["organization_id"], user, dashboard_id)
        except ModerationError as e:
            raise _bad(e)


@router.post("/dashboards/{dashboard_id}/moderate")
async def moderate(dashboard_id: str, body: DecideIn, user: dict = Depends(moderator)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.decide(
                    conn, user["organization_id"], user, dashboard_id, body.decision,
                    body.reason_code, body.comment, body.checklist)
        except ModerationError as e:
            raise _bad(e)


@router.get("/dashboards/{dashboard_id}/moderation-history")
async def moderation_history(dashboard_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.history(conn, user["organization_id"], dashboard_id)
        except ModerationError as e:
            raise _bad(e)
