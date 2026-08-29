"""HTTP: быстрый доступ (куратор-меню коротких названий отчётов, все роли)."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ... import db
from ..auth.deps import get_current_user, require_roles
from . import service
from .service import QuickLinkError

router = APIRouter(tags=["quicklinks"])
manage = require_roles("superadmin", "admin", "moderator")


class LinkIn(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    kind: str
    dashboard_id: Optional[str] = None
    section: Optional[str] = None


class ReorderIn(BaseModel):
    ids: List[str]


@router.get("/quick-links")
async def list_links(user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        return {"items": await service.list_links(conn, user["organization_id"], user)}


@router.get("/quick-links/allowed-sections")
async def allowed_sections(user: dict = Depends(manage)):
    """Список разделов, на которые можно ссылаться — для формы добавления пункта."""
    return {"sections": sorted(service.ALLOWED_SECTIONS)}


@router.post("/quick-links", status_code=status.HTTP_201_CREATED)
async def create_link(body: LinkIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.create_link(
                conn, user["organization_id"], user["id"], body.label, body.kind,
                body.dashboard_id, body.section)
        except QuickLinkError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.post("/quick-links/reorder")
async def reorder_links(body: ReorderIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            await service.reorder_links(conn, user["organization_id"], body.ids)
        except QuickLinkError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    return {"ok": True}


@router.delete("/quick-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_link(link_id: str, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        await service.delete_link(conn, user["organization_id"], link_id)
