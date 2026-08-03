"""Модуль «Витрины» (HTTP): подборки из N целых дашбордов на одном экране.

Создание/управление составом — admin/moderator; просмотр списка и содержимого
витрины — любой авторизованный (элементы фильтруются RLS дашбордов внутри
service.get_showcase)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ... import db
from ..auth.deps import get_current_user, require_roles
from . import service
from .service import ShowcasesError

router = APIRouter(prefix="/showcases", tags=["showcases"])
manage = require_roles("admin", "moderator")


def _bad(e: ShowcasesError) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if "не найден" in str(e) else status.HTTP_400_BAD_REQUEST
    return HTTPException(code, str(e))


class ShowcaseIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ItemIn(BaseModel):
    dashboard_id: str


class ReorderIn(BaseModel):
    item_id: str
    direction: str


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_showcase(body: ShowcaseIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.create_showcase(conn, user["organization_id"], user["id"], body.name)
        except ShowcasesError as e:
            raise _bad(e)


@router.get("")
async def list_showcases(user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        return await service.list_showcases(conn, user["organization_id"])


@router.get("/{showcase_id}")
async def get_showcase(showcase_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.get_showcase(conn, user["organization_id"], user, showcase_id)
        except ShowcasesError as e:
            raise _bad(e)


@router.delete("/{showcase_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_showcase(showcase_id: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            await service.delete_showcase(conn, user["organization_id"], showcase_id)
        except ShowcasesError as e:
            raise _bad(e)


@router.post("/{showcase_id}/items", status_code=status.HTTP_201_CREATED)
async def add_item(showcase_id: str, body: ItemIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.add_item(conn, user["organization_id"], user, showcase_id, body.dashboard_id)
        except ShowcasesError as e:
            raise _bad(e)


@router.delete("/{showcase_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_item(showcase_id: str, item_id: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            await service.remove_item(conn, user["organization_id"], showcase_id, item_id)
        except ShowcasesError as e:
            raise _bad(e)


@router.post("/{showcase_id}/reorder")
async def reorder_item(showcase_id: str, body: ReorderIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            await service.reorder_item(conn, user["organization_id"], showcase_id, body.item_id, body.direction)
            return {"ok": True}
        except ShowcasesError as e:
            raise _bad(e)
