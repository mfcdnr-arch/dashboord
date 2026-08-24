"""Быстрый поиск по системе (п. 9, Ctrl+K): один запрос сразу по пяти сущностям."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from ... import db
from ..auth.deps import get_current_user
from . import service

router = APIRouter(tags=["search"])


@router.get("/search")
async def search(q: str = Query(..., min_length=1), user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        return await service.search(conn, user["organization_id"], user, q)
