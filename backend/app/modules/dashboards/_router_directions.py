"""HTTP: направления дашбордов (этап 3, 29.09.2026).

Свой корневой префикс `/dashboard-directions`, а не `/dashboards/directions`:
под `/dashboards/…` любой статический путь, объявленный ниже
`/dashboards/{dashboard_id}`, перехватывается им (Starlette матчит по
порядку). Префикс обязан стоять в nginx.locations.conf и vite.config.ts —
это держит test_proxy_prefixes.

Чтение — любому авторизованному: зритель видит группы своих дашбордов.
Правка и назначение — управляющим (как перемещение в папку). Раскладку ВСЕГО
списка по предложению системы подтверждает администратор — решение заказчика
23.09 («система предлагает, админ подтверждает»).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ... import db
from ..auth.deps import get_current_user
from . import _directions as dirs
from ._router_base import _bad, admin_only, manage
from .service import DashboardError

router = APIRouter()


class DirectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=dirs.MAX_NAME)
    description: Optional[str] = Field(default=None, max_length=1000)


class DirectionPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=dirs.MAX_NAME)
    description: Optional[str] = Field(default=None, max_length=1000)


class ReorderIn(BaseModel):
    ids: List[str] = Field(max_length=500)


class AssignIn(BaseModel):
    dashboard_ids: List[str] = Field(min_length=1, max_length=500)
    # Существующее направление — по id; новое — по имени (совпавшее с уже
    # заведённым имя ведёт в него, второе не создаётся). Ни то ни другое —
    # снять направление.
    direction_id: Optional[str] = None
    new_name: Optional[str] = Field(default=None, max_length=dirs.MAX_NAME)


class ProposalGroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=dirs.MAX_NAME)
    dashboard_ids: List[str] = Field(max_length=500)


class ProposalApplyIn(BaseModel):
    groups: List[ProposalGroupIn] = Field(max_length=200)


@router.get("/dashboard-directions")
async def list_directions(user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        return await dirs.list_directions(conn, user["organization_id"], user)


@router.post("/dashboard-directions", status_code=201)
async def create_direction(body: DirectionIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await dirs.create_direction(conn, user["organization_id"], user["id"],
                                               body.name, body.description)
        except DashboardError as e:
            raise _bad(e)


# Статические пути — ДО /dashboard-directions/{direction_id}.
@router.post("/dashboard-directions/reorder")
async def reorder_directions(body: ReorderIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await dirs.reorder_directions(conn, user["organization_id"], body.ids)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboard-directions/assign")
async def assign_direction(body: AssignIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await dirs.assign(conn, user["organization_id"], user["id"],
                                         body.dashboard_ids, body.direction_id, body.new_name)
        except DashboardError as e:
            raise _bad(e)


@router.get("/dashboard-directions/proposal")
async def direction_proposal(user: dict = Depends(admin_only)):
    async with db.acquire(user["id"]) as conn:
        return await dirs.proposal(conn, user["organization_id"])


@router.post("/dashboard-directions/proposal/apply")
async def apply_direction_proposal(body: ProposalApplyIn, user: dict = Depends(admin_only)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await dirs.apply_proposal(conn, user["organization_id"], user["id"],
                                                 [g.model_dump() for g in body.groups])
        except DashboardError as e:
            raise _bad(e)


@router.get("/dashboard-directions/for-object/{object_id}")
async def direction_for_object(object_id: str, user: dict = Depends(manage)):
    """Направление по умолчанию для нового дашборда объекта (мастер сборки)."""
    async with db.acquire(user["id"]) as conn:
        return {"suggestion": await dirs.suggest_for_object(conn, user["organization_id"], object_id)}


@router.patch("/dashboard-directions/{direction_id}")
async def update_direction(direction_id: str, body: DirectionPatch, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await dirs.update_direction(conn, user["organization_id"], direction_id,
                                                   body.model_dump(exclude_unset=True))
        except DashboardError as e:
            raise _bad(e)


@router.delete("/dashboard-directions/{direction_id}")
async def delete_direction(direction_id: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await dirs.delete_direction(conn, user["organization_id"], direction_id)
        except DashboardError as e:
            raise _bad(e)
