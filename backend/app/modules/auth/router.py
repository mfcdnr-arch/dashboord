"""Модуль авторизации: вход (JWT) и текущий пользователь."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from ... import db
from ..system import settings_service as settings_svc
from .deps import get_current_user
from .security import create_token, hash_password, validate_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class ChangePasswordIn(BaseModel):
    new_password: str = Field(min_length=1, max_length=200)


@router.get("/password-policy")
async def password_policy():
    """Параметры парольной политики — чтобы UI показывал корректные подсказки
    и предпроверял пароль до отправки. Не секретно."""
    from ...config import settings
    return {
        "min_length": settings.password_min_length,
        "require_complexity": settings.password_require_complexity,
    }


@router.post("/login")
async def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    fwd = request.headers.get("x-forwarded-for")
    ip = (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else None)) or None
    ua = request.headers.get("user-agent")
    async with db.get_pool().acquire() as conn:
        sys_settings = await settings_svc.get_system_settings(conn)
        row = await conn.fetchrow(
            "select id, organization_id, password_hash, is_active from users where login = $1",
            form.username,
        )
        # Защита от подбора: блокировка по логину после N неудач за окно
        # (пороги настраиваются в UI «Настройки», а не только через .env).
        locked = False
        if sys_settings["login_max_attempts"] > 0:
            fails = await conn.fetchval(
                "select count(*) from login_events where login=$1 and success=false "
                "and created_at > now() - make_interval(mins => $2)",
                form.username, sys_settings["login_lockout_minutes"])
            locked = fails >= sys_settings["login_max_attempts"]
        ok = (not locked) and bool(row) and row["is_active"] and verify_password(form.password, row["password_hash"])
        await conn.execute(
            "insert into login_events(organization_id, user_id, login, ip, user_agent, success) "
            "values($1,$2,$3,$4,$5,$6)",
            row["organization_id"] if row else None, row["id"] if row else None,
            form.username, ip, ua, ok,
        )
    if locked:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Слишком много неудачных попыток. Повторите через {sys_settings['login_lockout_minutes']} мин.")
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    return {"access_token": create_token(str(row["id"])), "token_type": "bearer"}


@router.post("/change-password")
async def change_password(data: ChangePasswordIn, user: dict = Depends(get_current_user)):
    try:
        validate_password(data.new_password, user.get("login"))
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
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
