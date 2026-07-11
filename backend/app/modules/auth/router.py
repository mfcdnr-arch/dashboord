"""Модуль авторизации: вход (JWT) и текущий пользователь."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from ... import db
from .deps import get_current_user
from .security import create_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(form: OAuth2PasswordRequestForm = Depends()):
    async with db.get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "select id, password_hash, is_active from users where login = $1",
            form.username,
        )
    if row is None or not row["is_active"] or not verify_password(
        form.password, row["password_hash"]
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    return {"access_token": create_token(str(row["id"])), "token_type": "bearer"}


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
