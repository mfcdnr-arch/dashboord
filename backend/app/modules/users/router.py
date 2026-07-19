"""Модуль «Пользователи» (HTTP): отделы, роли, CRUD пользователей.

Управление пользователями — только роль admin. Жёсткого удаления нет,
только блокировка (is_active).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ... import db
from ..auth.deps import require_roles
from . import service
from .service import UsersError

router = APIRouter(tags=["users"])
admin = require_roles("admin")


def _bad(e: UsersError) -> HTTPException:
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
async def list_departments(user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        return await service.list_departments(conn, user["organization_id"])


@router.post("/departments", status_code=status.HTTP_201_CREATED)
async def create_department(body: DepartmentIn, user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.create_department(conn, user["organization_id"], body.name)
        except UsersError as e:
            raise _bad(e)


@router.delete("/departments/{department_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department(department_id: str, user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        try:
            await service.delete_department(conn, user["organization_id"], department_id)
        except UsersError as e:
            raise _bad(e)


# --- Роли (для выбора) ---
@router.get("/roles")
async def list_roles(user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        return await service.list_roles(conn, user["organization_id"])


# --- Аудит входов ---
@router.get("/login-events")
async def login_events(user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        return await service.login_events_report(conn, user["organization_id"])


# --- Пользователи ---
@router.get("/users")
async def list_users(user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        return await service.list_users(conn, user["organization_id"])


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(body: UserIn, user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        try:
            async with conn.transaction():
                return await service.create_user(
                    conn, user["organization_id"], body.login, body.password, body.last_name,
                    body.first_name, body.middle_name, body.email, body.department_id, body.role_ids)
        except UsersError as e:
            raise _bad(e)


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UserPatch, user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        try:
            async with conn.transaction():
                return await service.update_user(
                    conn, user["organization_id"], user_id, body.last_name, body.first_name,
                    body.middle_name, body.email, body.department_id, body.role_ids)
        except UsersError as e:
            raise _bad(e)


@router.post("/users/{user_id}/active")
async def set_active(user_id: str, body: ActiveIn, user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.set_active(conn, user["organization_id"], user_id, body.is_active, user["id"])
        except UsersError as e:
            raise _bad(e)


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: str, body: ResetPwIn, user: dict = Depends(admin)):
    async with db.get_pool().acquire() as conn:
        try:
            return await service.reset_password(conn, user["organization_id"], user_id, body.password)
        except UsersError as e:
            raise _bad(e)
