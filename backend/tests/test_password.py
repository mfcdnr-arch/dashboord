"""Парольная политика: смена пароля отклоняет слабые, принимает стойкий.
Используем viewer-токен (не admin), чтобы не трогать общую сессию admin/admin."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _change(client, headers, pw, current="viewer123"):
    # Текущий пароль обязателен (находка аудита) — фикстура `viewer` заводится
    # с этим паролем; здесь проверяется политика для НОВОГО пароля.
    return await client.post("/auth/change-password", headers=headers,
                             json={"current_password": current, "new_password": pw})


async def test_reject_too_short(client, viewer):
    r = await _change(client, viewer["headers"], "ab1")
    assert r.status_code == 400


async def test_reject_no_digit(client, viewer):
    r = await _change(client, viewer["headers"], "abcdefghij")
    assert r.status_code == 400


async def test_reject_common_weak(client, viewer):
    r = await _change(client, viewer["headers"], "password")
    assert r.status_code == 400


async def test_accept_strong(client, viewer):
    r = await _change(client, viewer["headers"], "Str0ngPass9")
    assert r.status_code == 200


async def test_password_policy_endpoint(client):
    # публичный (для подсказок UI): min_length + require_complexity
    r = await client.get("/auth/password-policy")
    assert r.status_code == 200
    body = r.json()
    assert body["min_length"] >= 1 and isinstance(body["require_complexity"], bool)
