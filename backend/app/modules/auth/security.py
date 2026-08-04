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
    # bcrypt по устройству учитывает только первые 72 БАЙТА пароля и молча
    # отбрасывает остальное: пользователь думал бы, что длинный пароль надёжнее,
    # а по факту проверялась бы лишь его отсечённая часть. Кириллица в UTF-8 —
    # 2 байта на символ, поэтому предел ≈36 русских символов. Лучше честно
    # отказать, чем тихо усечь.
    if len(pw.encode("utf-8")) > 72:
        raise ValueError(
            "Пароль слишком длинный: максимум 72 байта "
            "(≈72 латинских или ≈36 кириллических символов) — ограничение алгоритма bcrypt")
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
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_expire_minutes)
    # iat нужен для отзыва: токены, выданные ДО смены пароля, отвергаются
    # (см. users.password_changed_at, миграция 033).
    return jwt.encode(
        {"sub": subject, "exp": expire, "iat": now}, settings.jwt_secret, algorithm="HS256"
    )


def decode_token(token: str) -> str | None:
    """Совместимая форма: только subject (id пользователя) либо None."""
    payload = decode_token_payload(token)
    return payload.get("sub") if payload else None


def decode_token_payload(token: str) -> dict | None:
    """Полезная нагрузка токена (sub/exp/iat) либо None, если токен невалиден."""
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
