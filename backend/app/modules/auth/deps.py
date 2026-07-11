"""Зависимости авторизации: текущий пользователь из JWT."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from ... import db
from .security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    user_id = decode_token(token)
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный токен")
    async with db.get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "select id, login, full_name, is_active, must_change_password, organization_id "
            "from users where id = $1::uuid",
            user_id,
        )
    if row is None or not row["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден или заблокирован")
    return dict(row)
