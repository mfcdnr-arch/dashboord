"""HTTP: архив дашбордов (слепки, месячные папки, избирательный доступ).

Вынесено из router.py.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from ... import db
from ..auth.deps import get_current_user
from . import _archive
from ._router_base import _bad, admin_only, manage
from .service import DashboardError

router = APIRouter()


class ArchiveIn(BaseModel):
    topic: Optional[str] = Field(None, max_length=120)
    note: Optional[str] = Field(None, max_length=1000)


class AutoArchiveIn(BaseModel):
    enabled: bool


class ArchiveAccessIn(BaseModel):
    user_id: str


@router.post("/dashboards/{dashboard_id}/archive", status_code=status.HTTP_201_CREATED)
async def archive_dashboard(dashboard_id: str, body: ArchiveIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await _archive.archive_dashboard(conn, user["organization_id"], user,
                                                        dashboard_id, body.topic, body.note)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboards/{dashboard_id}/auto-archive")
async def set_auto_archive(dashboard_id: str, body: AutoArchiveIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await _archive.set_auto_archive(conn, user["organization_id"], user, dashboard_id, body.enabled)
        except DashboardError as e:
            raise _bad(e)


@router.get("/archive/me")
async def archive_me(user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        return {"allowed": await _archive.can_view_archive(conn, user["organization_id"], user)}


@router.get("/archive/months")
async def archive_months(user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await _archive.months(conn, user["organization_id"], user)
        except DashboardError as e:
            raise HTTPException(status_code=403, detail=str(e))


@router.get("/archive/topics")
async def archive_topics(user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await _archive.topics(conn, user["organization_id"], user)
        except DashboardError as e:
            raise HTTPException(status_code=403, detail=str(e))


@router.get("/archive")
async def archive_list(user: dict = Depends(get_current_user), month: Optional[str] = None,
                       q: Optional[str] = None, topic: Optional[str] = None,
                       from_date: Optional[str] = None, to_date: Optional[str] = None):
    async with db.acquire(user["id"]) as conn:
        try:
            return await _archive.list_archive(conn, user["organization_id"], user, month, q, topic,
                                               from_date=from_date, to_date=to_date)
        except DashboardError as e:
            raise HTTPException(status_code=403, detail=str(e))


@router.get("/archive/{archive_id}")
async def archive_get(archive_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await _archive.get_archive(conn, user["organization_id"], user, archive_id)
        except DashboardError as e:
            code = 403 if "доступа" in str(e) else 404
            raise HTTPException(status_code=code, detail=str(e))


@router.get("/archive/{archive_id}/export.xlsx")
async def archive_export(archive_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            a = await _archive.get_archive(conn, user["organization_id"], user, archive_id)
        except DashboardError as e:
            code = 403 if "доступа" in str(e) else 404
            raise HTTPException(status_code=code, detail=str(e))
    data = _archive.snapshot_to_xlsx(a)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="archive.xlsx"'},
    )


@router.post("/archive/{archive_id}/unarchive")
async def archive_unarchive(archive_id: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await _archive.unarchive(conn, user["organization_id"], user, archive_id)
        except DashboardError as e:
            raise _bad(e)


@router.delete("/archive/{archive_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_delete(archive_id: str, user: dict = Depends(admin_only)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                await _archive.delete_archive(conn, user["organization_id"], user, archive_id)
        except DashboardError as e:
            raise _bad(e)


@router.get("/archive-access")
async def archive_access_list(user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        return await _archive.list_access(conn, user["organization_id"])


@router.post("/archive-access", status_code=status.HTTP_201_CREATED)
async def archive_access_add(body: ArchiveAccessIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await _archive.add_access(conn, user["organization_id"], user["id"], body.user_id)
        except DashboardError as e:
            raise _bad(e)


@router.delete("/archive-access/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_access_remove(user_id: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        async with conn.transaction():
            await _archive.remove_access(conn, user["organization_id"], user["id"], user_id)
