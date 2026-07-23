"""Сервис справочников: услуги (services) и служебные документы (reference_documents).

Чтение — управляющие роли (нужны модератору при проверке), запись — админ.
"""
from __future__ import annotations

from typing import Optional


class CatalogError(Exception):
    """Доменная ошибка справочников."""


# --- Услуги ---------------------------------------------------------------
async def list_services(conn, org_id, include_inactive: bool = True) -> list:
    where = "organization_id=$1" + ("" if include_inactive else " and is_active")
    rows = await conn.fetch(
        f"select id, code, name, category, description, is_active, created_at "
        f"from services where {where} order by is_active desc, name", org_id)
    return [dict(r) for r in rows]


async def create_service(conn, org_id, code: str, name: str,
                         category: Optional[str], description: Optional[str]) -> dict:
    if await conn.fetchval("select 1 from services where organization_id=$1 and code=$2", org_id, code):
        raise CatalogError("Услуга с таким кодом уже есть")
    row = await conn.fetchrow(
        "insert into services(organization_id, code, name, category, description) "
        "values($1,$2,$3,$4,$5) returning id, code, name, category, description, is_active, created_at",
        org_id, code, name, category, description)
    return dict(row)


async def update_service(conn, org_id, service_id: str, name: Optional[str], category: Optional[str],
                         description: Optional[str], is_active: Optional[bool]) -> dict:
    row = await conn.fetchrow(
        "update services set name=coalesce($3,name), category=coalesce($4,category), "
        "description=coalesce($5,description), is_active=coalesce($6,is_active) "
        "where id=$1::uuid and organization_id=$2 "
        "returning id, code, name, category, description, is_active, created_at",
        service_id, org_id, name, category, description, is_active)
    if row is None:
        raise CatalogError("Услуга не найдена")
    return dict(row)


async def delete_service(conn, org_id, service_id: str) -> None:
    res = await conn.execute(
        "delete from services where id=$1::uuid and organization_id=$2", service_id, org_id)
    if res.endswith("0"):
        raise CatalogError("Услуга не найдена")


# --- Служебные документы --------------------------------------------------
async def list_reference_docs(conn, org_id) -> list:
    rows = await conn.fetch(
        "select id, title, description, url, created_at from reference_documents "
        "where organization_id=$1 order by title", org_id)
    return [dict(r) for r in rows]


async def create_reference_doc(conn, org_id, title: str, description: Optional[str],
                               url: Optional[str]) -> dict:
    row = await conn.fetchrow(
        "insert into reference_documents(organization_id, title, description, url) "
        "values($1,$2,$3,$4) returning id, title, description, url, created_at",
        org_id, title, description, url)
    return dict(row)


async def delete_reference_doc(conn, org_id, doc_id: str) -> None:
    res = await conn.execute(
        "delete from reference_documents where id=$1::uuid and organization_id=$2", doc_id, org_id)
    if res.endswith("0"):
        raise CatalogError("Документ не найден")
