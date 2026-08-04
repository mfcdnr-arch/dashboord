"""Модуль авторизации: вход (JWT) и текущий пользователь."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from ... import db
from ..appeals import service as appeals_svc
from ..system import settings_service as settings_svc
from .deps import get_current_user
from .security import create_token, hash_password, validate_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class ChangePasswordIn(BaseModel):
    new_password: str = Field(min_length=1, max_length=200)


class BlockedAppealIn(BaseModel):
    login: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4000)


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
        # Пароль верен независимо от is_active — иначе посторонний, не зная
        # пароля, мог бы узнать, что чужой аккаунт заблокирован (перебором логинов).
        pwd_ok = (not locked) and bool(row) and verify_password(form.password, row["password_hash"])
        blocked = pwd_ok and not row["is_active"]
        ok = pwd_ok and row["is_active"]
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
    if blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, {
            "code": "account_blocked",
            "message": "Учётная запись заблокирована администратором. Опишите проблему — обращение будет передано.",
        })
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    return {"access_token": create_token(str(row["id"])), "token_type": "bearer"}


@router.post("/blocked-appeal", status_code=status.HTTP_204_NO_CONTENT)
async def blocked_appeal(body: BlockedAppealIn):
    """Обращение от заблокированного аккаунта — БЕЗ авторизации (войти он не
    может). Ответ одинаков независимо от того, найден ли логин — иначе можно
    было бы перебором логинов узнавать, какие учётки существуют."""
    async with db.acquire() as conn:
        await appeals_svc.create_appeal_by_login(conn, body.login, body.message)


@router.post("/change-password")
async def change_password(data: ChangePasswordIn, user: dict = Depends(get_current_user)):
    try:
        validate_password(data.new_password, user.get("login"))
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    async with db.get_pool().acquire() as conn:
        # password_changed_at отзывает ВСЕ ранее выданные токены (миграция 033),
        # включая текущий — поэтому сразу выдаём новый, чтобы пользователь не
        # получил 401 на следующем же запросе после смены пароля.
        await conn.execute(
            "update users set password_hash = $1, must_change_password = false, "
            "password_changed_at = date_trunc('second', now()) where id = $2",
            hash_password(data.new_password), user["id"],
        )
    return {"status": "ok", "access_token": create_token(str(user["id"])), "token_type": "bearer"}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        # code — для гейтинга прав на фронте (App.tsx), name — человекочитаемо
        # для профиля. Отдаём оба сразу: GET /roles (каталог) доступен только
        # admin/superadmin, обычный пользователь иначе не смог бы перевести
        # собственные роли в профиле.
        roles = await conn.fetch(
            "select r.code, r.name from user_roles ur join roles r on r.id = ur.role_id "
            "where ur.user_id = $1",
            user["id"],
        )
        # Доп. поля — для личного кабинета (профиль), не только для гейтинга ролей.
        extra = await conn.fetchrow(
            "select u.email, u.last_name, u.first_name, u.middle_name, u.created_at, "
            "d.name as department_name "
            "from users u left join departments d on d.id = u.department_id where u.id = $1",
            user["id"],
        )
    return {
        "id": str(user["id"]),
        "login": user["login"],
        "full_name": user["full_name"],
        "must_change_password": user["must_change_password"],
        "roles": [r["code"] for r in roles],
        "role_names": [r["name"] for r in roles],
        "email": extra["email"],
        "last_name": extra["last_name"],
        "first_name": extra["first_name"],
        "middle_name": extra["middle_name"],
        "department_name": extra["department_name"],
        "created_at": extra["created_at"],
    }
