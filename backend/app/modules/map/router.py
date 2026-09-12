"""Раздел «Карта» (HTTP): справочник отделений МФЦ и геометрия контура.

Чтение — любой авторизованный: адрес, телефон и режим работы отделения нужны
и обычному пользователю, ради него карта и заводится. Запись — администратор,
как и у остальных справочников.

Порядок маршрутов важен: `/offices/import` и `/offices/unmatched` объявлены ДО
`/offices/{office_id}`, иначе слово «import» уедет в параметр пути.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ... import db
from ..auth.deps import get_current_user, require_roles
from ..system import settings_service
from . import service
from .service import MapError

router = APIRouter(prefix="/map", tags=["map"])
manage = require_roles("admin", "superadmin")

MAX_IMPORT_BYTES = 5 * 1024 * 1024  # перечень отделений — это десятки килобайт


def _bad(e: MapError) -> HTTPException:
    code = status.HTTP_404_NOT_FOUND if "не найден" in str(e) else status.HTTP_400_BAD_REQUEST
    return HTTPException(code, str(e))


class OfficeIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    address: Optional[str] = Field(default=None, max_length=500)
    city: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=100)
    phone2: Optional[str] = Field(default=None, max_length=100)
    email: Optional[str] = Field(default=None, max_length=200)
    website: Optional[str] = Field(default=None, max_length=300)
    hours: Optional[dict] = None
    note: Optional[str] = Field(default=None, max_length=2000)
    lat: Optional[float] = None
    lon: Optional[float] = None
    row_label: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None


class OfficePatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=300)
    address: Optional[str] = Field(default=None, max_length=500)
    city: Optional[str] = Field(default=None, max_length=200)
    phone: Optional[str] = Field(default=None, max_length=100)
    phone2: Optional[str] = Field(default=None, max_length=100)
    email: Optional[str] = Field(default=None, max_length=200)
    website: Optional[str] = Field(default=None, max_length=300)
    hours: Optional[dict] = None
    note: Optional[str] = Field(default=None, max_length=2000)
    lat: Optional[float] = None
    lon: Optional[float] = None
    row_label: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None


class MapSettingsIn(BaseModel):
    # Набор данных, по которому система сверяет, не появилось ли в отчёте
    # отделение, которого нет на карте.
    map_dataset_code: Optional[str] = Field(default=None, max_length=100)


# --- Геометрия ------------------------------------------------------------

@router.get("/geo/contour")
async def geo_contour(user: dict = Depends(get_current_user)):
    """Контур республики. Лежит в бэкенде, чтобы проверка координат и отрисовка
    карты брали ОДНУ геометрию (и чтобы её можно было заменить официальной, не
    пересобирая фронт)."""
    return JSONResponse(service.contour(), headers={"Cache-Control": "public, max-age=86400"})


# --- Справочник отделений -------------------------------------------------

@router.get("/offices")
async def list_offices(q: Optional[str] = None, only_active: bool = False,
                       user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        return await service.list_offices(conn, user["organization_id"], q, only_active)


@router.post("/offices/import")
async def import_offices(file: UploadFile = File(...), update_existing: bool = Query(False),
                         user: dict = Depends(manage)):
    raw = await file.read()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Файл пустой")
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Файл слишком большой (предел 5 МБ)")
    async with db.get_pool().acquire() as conn:
        async with conn.transaction():
            try:
                return await service.import_csv(conn, user["organization_id"], user["id"],
                                                raw, update_existing)
            except MapError as e:
                raise _bad(e)


@router.get("/offices/unmatched")
async def unmatched(dataset_code: Optional[str] = None, user: dict = Depends(manage)):
    """Строки отчёта, которым не сопоставлено отделение. Без явного набора
    данных берётся тот, что выбран в настройках раздела."""
    async with db.get_pool().acquire() as conn:
        code = dataset_code or (await settings_service.get_org_settings(
            conn, user["organization_id"])).get("map_dataset_code")
        if not code:
            return {"dataset_code": None, "rows_total": 0, "linked": 0,
                    "unmatched": [], "offices_without_row": [],
                    "hint": "Выберите отчёт, по которому сверять отделения"}
        try:
            return await service.unmatched(conn, user["organization_id"], code)
        except MapError as e:
            raise _bad(e)


@router.post("/offices/link-suggested")
async def link_suggested(dataset_code: Optional[str] = None, user: dict = Depends(manage)):
    """Связать разом все строки отчёта с однозначной подсказкой."""
    async with db.get_pool().acquire() as conn:
        code = dataset_code or (await settings_service.get_org_settings(
            conn, user["organization_id"])).get("map_dataset_code")
        if not code:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Сначала выберите отчёт, по которому сверяются отделения")
        async with conn.transaction():
            try:
                return await service.link_suggested(conn, user["organization_id"], user["id"], code)
            except MapError as e:
                raise _bad(e)


@router.get("/offices/{office_id}")
async def get_office(office_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.get_office(conn, user["organization_id"], office_id)
        except MapError as e:
            raise _bad(e)


@router.post("/offices", status_code=status.HTTP_201_CREATED)
async def create_office(body: OfficeIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        async with conn.transaction():
            try:
                return await service.create_office(conn, user["organization_id"], user["id"],
                                                   body.model_dump(exclude_unset=True))
            except MapError as e:
                raise _bad(e)


@router.patch("/offices/{office_id}")
async def update_office(office_id: str, body: OfficePatch, user: dict = Depends(manage)):
    patch: dict[str, Any] = body.model_dump(exclude_unset=True)
    async with db.get_pool().acquire() as conn:
        async with conn.transaction():
            try:
                return await service.update_office(conn, user["organization_id"], user["id"],
                                                   office_id, patch)
            except MapError as e:
                raise _bad(e)


@router.delete("/offices/{office_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_office(office_id: str, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        async with conn.transaction():
            try:
                await service.delete_office(conn, user["organization_id"], user["id"], office_id)
            except MapError as e:
                raise _bad(e)


# --- Настройки раздела ----------------------------------------------------

@router.get("/settings")
async def get_settings(user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        s = await settings_service.get_org_settings(conn, user["organization_id"])
        return {"map_dataset_code": s.get("map_dataset_code") or None}


@router.put("/settings")
async def put_settings(body: MapSettingsIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        s = await settings_service.update_org_settings(
            conn, user["organization_id"], {"map_dataset_code": body.map_dataset_code or ""})
        return {"map_dataset_code": s.get("map_dataset_code") or None}
