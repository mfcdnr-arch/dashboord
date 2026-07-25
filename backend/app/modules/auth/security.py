"""Хэширование паролей (bcrypt) и JWT-токены."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from ...config import settings


# Распространённые слабые пароли — отклоняются политикой независимо от длины.
_COMMON_WEAK = {
    "password", "passw0rd", "пароль", "123456", "1234567", "12345678", "123456789",
    "1234567890", "qwerty", "qwerty123", "admin", "admin123", "111111", "000000",
    "dashbord", "dashboard", "iloveyou", "welcome",
}


def validate_password(password: str, login: str | None = None) -> None:
    """Проверка пароля по политике (config). Бросает ValueError с понятным
    сообщением; вызывающий переводит его в 400. НЕ используется для первичного
    admin из bootstrap (там пароль задаётся деплойщиком через ADMIN_PASSWORD)."""
    pw = password or ""
    if len(pw) < settings.password_min_length:
        raise ValueError(f"Пароль слишком короткий: минимум {settings.password_min_length} символов")
    if len(pw) > 200:
        raise ValueError("Пароль слишком длинный (максимум 200 символов)")
    if settings.password_require_complexity and (
        not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw)
    ):
        raise ValueError("Пароль должен содержать и буквы, и цифры")
    if login and pw.lower() == login.lower():
        raise ValueError("Пароль не должен совпадать с логином")
    if pw.lower() in _COMMON_WEAK:
        raise ValueError("Пароль слишком простой — выберите менее распространённый")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode(
        {"sub": subject, "exp": expire}, settings.jwt_secret, algorithm="HS256"
    )


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
