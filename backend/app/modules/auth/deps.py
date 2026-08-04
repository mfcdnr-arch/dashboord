"""Зависимости авторизации: текущий пользователь из JWT."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from ... import db
from .security import decode_token_payload

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Пока пароль временный (must_change_password), доступ разрешён ТОЛЬКО к смене
# пароля и своему профилю — иначе можно было бы пользоваться API, не сменив
# выданный админом временный пароль (обход обязательной смены).
_ALLOWED_BEFORE_PW_CHANGE = {"/auth/change-password", "/auth/me"}


async def get_current_user(request: Request, token: str = Depends(oauth2_scheme)) -> dict:
    payload = decode_token_payload(token)
    user_id = payload.get("sub") if payload else None
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный токен")
    async with db.get_pool().acquire() as conn:
        # Роли забираем ЗДЕСЬ же (array_agg), а не отдельным запросом в
        # require_roles: на каждый HTTP-запрос было два обращения к БД вместо
        # одного. Кэшировать роли в Redis сознательно НЕ стали — отзыв прав
        # должен действовать немедленно, а не через TTL.
        row = await conn.fetchrow(
            "select u.id, u.login, u.full_name, u.is_active, u.must_change_password, "
            "u.organization_id, u.password_changed_at, "
            "coalesce((select array_agg(r.code) from user_roles ur join roles r on r.id = ur.role_id "
            "          where ur.user_id = u.id), '{}') as role_codes "
            "from users u where u.id = $1::uuid",
            user_id,
        )
    if row is None or not row["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден или заблокирован")
    # Отзыв токенов, выданных до смены/сброса пароля (миграция 033). Токены,
    # выпущенные до внедрения (без iat) — не трогаем: у таких пользователей
    # password_changed_at пуст, пока пароль не менялся.
    changed_at = row["password_changed_at"]
    if changed_at is not None:
        iat = payload.get("iat") if payload else None
        issued = datetime.fromtimestamp(iat, tz=timezone.utc) if iat else None
        # Обе стороны сравниваются с точностью до СЕКУНДЫ: `iat` в JWT — целое
        # число секунд, поэтому и password_changed_at пишется через
        # date_trunc('second', now()). Иначе токен, выданный самой операцией
        # смены пароля, оказался бы «старше» отметки и умер бы сразу.
        # Гарантия: токены, выпущенные в ПРЕДЫДУЩИЕ секунды, недействительны.
        if issued is None or issued < changed_at:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пароль был изменён — войдите заново")
    if row["must_change_password"] and request.url.path not in _ALLOWED_BEFORE_PW_CHANGE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Сначала смените временный пароль")
    user = dict(row)
    user["roles"] = list(user.pop("role_codes") or [])
    return user


def require_roles(*codes: str):
    """Зависимость: пропускает только пользователей с одной из указанных ролей."""

    async def dep(user: dict = Depends(get_current_user)) -> dict:
        if not set(user.get("roles") or ()) & set(codes):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return user

    return dep
