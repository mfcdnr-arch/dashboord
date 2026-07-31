"""Просмотр логов через Loki (/system/logs) — фаза 2б.

В dev/CI мониторинг (Loki) не поднят, поэтому основной сценарий здесь —
"недоступен, но без 500" (available: false + подсказка), а не сами строки.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import hdr, login  # noqa: E402
from app import db  # noqa: E402
from app.modules.system import logs_service  # noqa: E402


async def test_logs_unavailable_when_loki_down_returns_hint_not_500(client, admin_headers):
    r = await client.get("/system/logs", params={"service": "api"}, headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is False
    assert body["lines"] == []
    assert "мониторинг" in body["hint"].lower() or "loki" in body["hint"].lower()
    assert "api" in body["services"]


async def test_logs_unknown_service_rejected(client, admin_headers):
    r = await client.get("/system/logs", params={"service": "nginx-does-not-exist"}, headers=admin_headers)
    assert r.status_code == 422, r.text


async def test_logs_forbidden_for_regular_user(client, admin_headers):
    roles = {x["code"]: x["id"] for x in (await client.get("/roles", headers=admin_headers)).json()}
    try:
        await client.post("/users", json={
            "login": "ztest_logs", "password": "Xy345678", "role_ids": [roles["user"]]}, headers=admin_headers)
        tok = await login(client, "ztest_logs", "Xy345678")
        r = await client.get("/system/logs", params={"service": "api"}, headers=hdr(tok))
        assert r.status_code == 403
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from user_roles where user_id in (select id from users where login='ztest_logs')")
            await conn.execute("delete from users where login='ztest_logs'")


async def test_query_logs_parses_and_sorts_loki_response(monkeypatch):
    """Юнит-тест разбора ответа Loki: несколько потоков -> плоский список,
    отсортированный по времени (новые сверху), обрезанный до limit."""
    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"result": [
                {"stream": {"service": "api"}, "values": [["100", "first"], ["300", "third"]]},
                {"stream": {"service": "api"}, "values": [["200", "second"]]},
            ]}}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, params=None):
            assert "loki" in url
            return FakeResp()

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient())

    lines = await logs_service.query_logs("api", minutes=30, limit=2, query=None)
    assert [ln["line"] for ln in lines] == ["third", "second"]  # новые сверху, обрезано до limit=2
