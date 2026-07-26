"""Модуль «Справочники» (HTTP): услуги + служебные документы.

Чтение — admin/moderator/senior_moderator (модератор сверяется при проверке).
Запись — только admin.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ... import db
from ..auth.deps import require_roles
from . import service
from .service import CatalogError

router = APIRouter(prefix="/catalog", tags=["catalog"])
read_roles = require_roles("admin", "moderator", "senior_moderator")
admin = require_roles("admin", "superadmin")


def _bad(e: CatalogError) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if "не найден" in str(e) else status.HTTP_400_BAD_REQUEST
    return HTTPException(code, str(e))


class ServiceIn(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    category: Optional[str] = None
    description: Optional[str] = None


class ServicePatch(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class RefDocIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: Optional[str] = None
    url: Optional[str] = None


# --- Услуги ---
@router.get("/services")
async def list_services(user: dict = Depends(read_roles)):
    async with db.get_pool().acquire() as conn:
        return await service.list_services(conn, user["organization_id"])


@router.post("/services", status_code=status.HTTP_201_CREATED)
async def create_service(body: ServiceIn, user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.create_service(conn, user["organization_id"], body.code,
                                                body.name, body.category, body.description)
        except CatalogError as e:
            raise _bad(e)


@router.patch("/services/{service_id}")
async def update_service(service_id: str, body: ServicePatch, user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.update_service(conn, user["organization_id"], service_id,
                                                body.name, body.category, body.description, body.is_active)
        except CatalogError as e:
            raise _bad(e)


@router.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(service_id: str, user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        try:
            await service.delete_service(conn, user["organization_id"], service_id)
        except CatalogError as e:
            raise _bad(e)


# --- Служебные документы ---
@router.get("/reference-docs")
async def list_reference_docs(user: dict = Depends(read_roles)):
    async with db.get_pool().acquire() as conn:
        return await service.list_reference_docs(conn, user["organization_id"])


@router.post("/reference-docs", status_code=status.HTTP_201_CREATED)
async def create_reference_doc(body: RefDocIn, user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        return await service.create_reference_doc(conn, user["organization_id"],
                                                  body.title, body.description, body.url)


@router.delete("/reference-docs/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reference_doc(doc_id: str, user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        try:
            await service.delete_reference_doc(conn, user["organization_id"], doc_id)
        except CatalogError as e:
            raise _bad(e)
