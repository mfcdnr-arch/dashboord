"""Модуль «Пользователи» (HTTP): отделы, роли, CRUD пользователей.

Управление пользователями — только роль admin. Жёсткого удаления нет,
только блокировка (is_active).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from ... import db
from ...exports import to_csv, to_xlsx
from ..audit.router import audit_reader
from ..auth.deps import get_current_user, require_roles
from . import service
from .service import UsersError, UsersForbidden

router = APIRouter(tags=["users"])
# Управление пользователями — admin и superadmin. Разграничение действий по
# иерархии (кто кого может трогать) — в service.py.
manage = require_roles("admin", "superadmin")
CSV_MEDIA = "text/csv; charset=utf-8"
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _attach(name: str) -> dict:
    return {"Content-Disposition": f'attachment; filename="{name}"'}


def _bad(e: UsersError) -> HTTPException:
    if isinstance(e, UsersForbidden):
        return HTTPException(status.HTTP_403_FORBIDDEN, str(e))
    code = status.HTTP_404_NOT_FOUND if "не найден" in str(e) else status.HTTP_400_BAD_REQUEST
    return HTTPException(code, str(e))


class DepartmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class UserIn(BaseModel):
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=4, max_length=200)
    last_name: Optional[str] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    email: Optional[str] = None
    department_id: Optional[str] = None
    role_ids: List[str] = []


class UserPatch(BaseModel):
    last_name: Optional[str] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    email: Optional[str] = None
    department_id: Optional[str] = None
    role_ids: Optional[List[str]] = None


class ActiveIn(BaseModel):
    is_active: bool


class ResetPwIn(BaseModel):
    password: str = Field(min_length=4, max_length=200)


# --- Отделы ---
@router.get("/departments")
async def list_departments(user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        return await service.list_departments(conn, user["organization_id"])


@router.post("/departments", status_code=status.HTTP_201_CREATED)
async def create_department(body: DepartmentIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.create_department(conn, user["organization_id"], body.name)
        except UsersError as e:
            raise _bad(e)


@router.delete("/departments/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department(department_id: str, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            await service.delete_department(conn, user["organization_id"], department_id)
        except UsersError as e:
            raise _bad(e)


# --- Роли (для выбора) ---
@router.get("/roles")
async def list_roles(user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        return await service.list_roles(conn, user["organization_id"])


@router.get("/users/me/activity")
async def get_my_activity(user: dict = Depends(get_current_user)):
    """Своя активность — личный кабинет (волна C). В отличие от
    /users/{id}/activity ниже, доступ не через audit_reader (это не аудит
    ЧУЖИХ действий) — любой смотрит только себя. ВАЖНО: регистрировать ДО
    параметризованного /users/{user_id}/activity, иначе Starlette матчит
    "me" как user_id и уводит на 403 audit_reader раньше, чем сюда."""
    async with db.get_pool().acquire() as conn:
        return await service.user_activity(conn, user["organization_id"], user["id"])


@router.get("/users/{user_id}/activity")
async def get_user_activity(user_id: str, user: dict = Depends(audit_reader)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.user_activity(conn, user["organization_id"], user_id)
        except UsersError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


# --- Аудит входов --- (доступ как у /audit: superadmin всегда, admin — по гранту)
@router.get("/login-events")
async def login_events(user: dict = Depends(audit_reader)):
    async with db.get_pool().acquire() as conn:
        return await service.login_events_report(conn, user["organization_id"])


@router.get("/login-events/export.csv")
async def export_login_csv(user: dict = Depends(audit_reader)):
    async with db.get_pool().acquire() as conn:
        headers, rows = await service.login_events_export(conn, user["organization_id"])
    return Response(to_csv(headers, rows), media_type=CSV_MEDIA, headers=_attach("login-events.csv"))


@router.get("/login-events/export.xlsx")
async def export_login_xlsx(user: dict = Depends(audit_reader)):
    async with db.get_pool().acquire() as conn:
        headers, rows = await service.login_events_export(conn, user["organization_id"])
    return Response(to_xlsx("Журнал входов", headers, rows), media_type=XLSX_MEDIA, headers=_attach("login-events.xlsx"))


# --- Пользователи ---
@router.get("/users")
async def list_users(user: dict = Depends(manage), q: Optional[str] = None,
                     limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    async with db.get_pool().acquire() as conn:
        return await service.list_users(conn, user["organization_id"], q=q, limit=limit, offset=offset)


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(body: UserIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            async with conn.transaction():
                return await service.create_user(
                    conn, user["organization_id"], body.login, body.password, body.last_name,
                    body.first_name, body.middle_name, body.email, body.department_id, body.role_ids, user)
        except UsersError as e:
            raise _bad(e)


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UserPatch, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            async with conn.transaction():
                return await service.update_user(
                    conn, user["organization_id"], user_id, body.last_name, body.first_name,
                    body.middle_name, body.email, body.department_id, body.role_ids, user)
        except UsersError as e:
            raise _bad(e)


@router.post("/users/{user_id}/active")
async def set_active(user_id: str, body: ActiveIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.set_active(conn, user["organization_id"], user_id, body.is_active, user)
        except UsersError as e:
            raise _bad(e)


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: str, body: ResetPwIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.reset_password(conn, user["organization_id"], user_id, body.password, user)
        except UsersError as e:
            raise _bad(e)


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.delete_user(conn, user["organization_id"], user_id, user)
        except UsersError as e:
            raise _bad(e)
