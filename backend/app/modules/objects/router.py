"""Модуль «Объекты»: объекты и папки внутри них.

Объект — верхний контейнер; внутри объекта заводятся папки, куда позже
загружаются документы. Управляют admin/moderator; чтение — любой авторизованный.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ... import db
from ..auth.deps import get_current_user, require_roles

router = APIRouter(prefix="/objects", tags=["objects"])

manage = require_roles("admin", "moderator")


class ObjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class FolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    parent_folder_id: Optional[str] = None


@router.get("")
async def list_objects(user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        rows = await conn.fetch(
            "select o.id, o.name, o.description, o.created_at, "
            "(select count(*) from folders f where f.object_id = o.id) as folders_count "
            "from objects o where o.organization_id = $1 order by o.name",
            user["organization_id"],
        )
    return [dict(r) for r in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_object(data: ObjectIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        exists = await conn.fetchval(
            "select 1 from objects where organization_id=$1 and name=$2",
            user["organization_id"], data.name,
        )
        if exists:
            raise HTTPException(status.HTTP_409_CONFLICT, "Объект с таким именем уже есть")
        row = await conn.fetchrow(
            "insert into objects(organization_id, name, description, created_by) "
            "values($1,$2,$3,$4) returning id, name, description, created_at",
            user["organization_id"], data.name, data.description, user["id"],
        )
    return dict(row)


@router.get("/{object_id}/folders")
async def list_folders(object_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        obj = await conn.fetchval(
            "select 1 from objects where id=$1::uuid and organization_id=$2",
            object_id, user["organization_id"],
        )
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
        rows = await conn.fetch(
            "select id, name, parent_folder_id, created_at from folders "
            "where object_id=$1::uuid order by name",
            object_id,
        )
    return [dict(r) for r in rows]


@router.post("/{object_id}/folders", status_code=status.HTTP_201_CREATED)
async def create_folder(object_id: str, data: FolderIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        obj = await conn.fetchval(
            "select 1 from objects where id=$1::uuid and organization_id=$2",
            object_id, user["organization_id"],
        )
        if not obj:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
        row = await conn.fetchrow(
            "insert into folders(organization_id, object_id, parent_folder_id, name, created_by) "
            "values($1,$2::uuid,$3::uuid,$4,$5) returning id, name, parent_folder_id, created_at",
            user["organization_id"], object_id, data.parent_folder_id, data.name, user["id"],
        )
    return dict(row)
