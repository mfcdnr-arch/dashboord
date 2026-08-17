"""Модуль «Обращения» (HTTP): заявки пользователей к администратору/модератору.

Создать и переписываться может любой авторизованный пользователь — в рамках
СВОИХ обращений; staff (admin/moderator/senior_moderator/superadmin) видит и
отвечает на все обращения организации. Разграничение — внутри service.py
(роли читаются из БД, а не только из зависимости, т.к. общий эндпоинт
/appeals/{id} и /appeals/{id}/messages обслуживает обе стороны).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from ... import db
from ..auth.deps import get_current_user, require_roles
from . import service
from .service import AppealsError, AppealsRateLimited

router = APIRouter(tags=["appeals"])
staff = require_roles("admin", "moderator", "senior_moderator", "superadmin")


def _bad(e: AppealsError) -> HTTPException:
    if isinstance(e, AppealsRateLimited):
        # Не ошибка ввода, а просьба подождать: 429 отличает «вы написали
        # лишнего» от «форма заполнена неверно», и интерфейс говорит об этом
        # человеческим текстом, а не подсвечивает поле.
        return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e))
    code = status.HTTP_404_NOT_FOUND if "не найдено" in str(e) else status.HTTP_400_BAD_REQUEST
    return HTTPException(code, str(e))


class AppealIn(BaseModel):
    subject: Optional[str] = None
    body: str = Field(min_length=1, max_length=4000)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


@router.post("/appeals", status_code=status.HTTP_201_CREATED)
async def create_appeal(body: AppealIn, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.create_appeal(conn, user["organization_id"], user, body.subject, body.body)
        except AppealsError as e:
            raise _bad(e)


class AccessRequestIn(BaseModel):
    wanted: str = Field(min_length=1, max_length=2000)


@router.post("/appeals/access-request", status_code=status.HTTP_201_CREATED)
async def access_request(body: AccessRequestIn, user: dict = Depends(get_current_user)):
    """«Мне нужен отчёт, которого я не вижу» (п. 15). Списка недоступных отчётов
    человеку не показываем — даже названия говорят, какие показатели за кем
    закреплены; он называет отчёт сам, а запрос приходит с его именем."""
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.create_access_request(conn, user["organization_id"], user, body.wanted)
        except AppealsError as e:
            raise _bad(e)


@router.get("/appeals/mine")
async def list_mine(user: dict = Depends(get_current_user),
                    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    async with db.acquire(user["id"]) as conn:
        return await service.list_mine(conn, user["id"], limit, offset)


@router.get("/appeals/stats")
async def stats(user: dict = Depends(staff)):
    async with db.acquire(user["id"]) as conn:
        return await service.open_count(conn, user["organization_id"])


@router.get("/appeals")
async def list_all(user: dict = Depends(staff), status_filter: Optional[str] = Query(None, alias="status"),
                   limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    async with db.acquire(user["id"]) as conn:
        return await service.list_org(conn, user["organization_id"], status_filter, limit, offset)


@router.get("/appeals/{appeal_id}")
async def get_appeal(appeal_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.get_appeal(conn, user["organization_id"], user, appeal_id)
        except AppealsError as e:
            raise _bad(e)


@router.post("/appeals/{appeal_id}/messages", status_code=status.HTTP_201_CREATED)
async def add_message(appeal_id: str, body: MessageIn, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.add_message(conn, user["organization_id"], user, appeal_id, body.body)
        except AppealsError as e:
            raise _bad(e)


@router.post("/appeals/{appeal_id}/close")
async def close_appeal(appeal_id: str, user: dict = Depends(staff)):
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.close_appeal(conn, user["organization_id"], user, appeal_id)
        except AppealsError as e:
            raise _bad(e)
