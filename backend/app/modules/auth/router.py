"""Модуль авторизации: вход (JWT) и текущий пользователь."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from ... import db
from .deps import get_current_user
from .security import create_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class ChangePasswordIn(BaseModel):
    new_password: str = Field(min_length=6, max_length=200)


@router.post("/login")
async def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    fwd = request.headers.get("x-forwarded-for")
    ip = (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)) or None
    ua = request.headers.get("user-agent")
    async with db.get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "select id, organization_id, password_hash, is_active from users where login = $1",
            form.username,
        )
        ok = bool(row) and row["is_active"] and verify_password(form.password, row["password_hash"])
        await conn.execute(
            "insert into login_events(organization_id, user_id, login, ip, user_agent, success) "
            "values($1,$2,$3,$4,$5,$6)",
            row["organization_id"] if row else None, row["id"] if row else None,
            form.username, ip, ua, ok,
        )
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    return {"access_token": create_token(str(row["id"])), "token_type": "bearer"}


@router.post("/change-password")
async def change_password(data: ChangePasswordIn, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        await conn.execute(
            "update users set password_hash = $1, must_change_password = false where id = $2",
            hash_password(data.new_password), user["id"],
        )
    return {"status": "ok"}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        roles = await conn.fetch(
            "select r.code from user_roles ur join roles r on r.id = ur.role_id "
            "where ur.user_id = $1",
            user["id"],
        )
    return {
        "id": str(user["id"]),
        "login": user["login"],
        "full_name": user["full_name"],
        "must_change_password": user["must_change_password"],
        "roles": [r["code"] for r in roles],
    }
