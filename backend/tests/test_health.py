"""Здоровье системы (/reports/system) + автопочинка (/maintenance/heal)."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import hdr, login  # noqa: E402
from app import db  # noqa: E402


async def test_system_report_has_status_and_latency(client, admin_headers):
    r = await client.get("/reports/system", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") in ("ok", "degraded")
    names = {s["name"] for s in body["services"]}
    assert {"PostgreSQL", "Redis", "MinIO"} <= names
    for s in body["services"]:
        assert "ok" in s and "latency_ms" in s


async def test_heal_returns_actions_for_admin(client, admin_headers):
    r = await client.post("/maintenance/heal", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "healthy" in body and isinstance(body["actions"], list)
    names = {a["name"] for a in body["actions"]}
    assert any("MinIO" in n for n in names)


async def test_prometheus_metrics_exposed(client, admin_headers):
    """Наблюдаемость: /internal/metrics отдаёт метрики в формате Prometheus."""
    await client.get("/health")  # сгенерировать хотя бы один запрос
    r = await client.get("/internal/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers.get("content-type", "")
    body = r.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body


async def test_heal_forbidden_for_regular_user(client, admin_headers):
    roles = {x["code"]: x["id"] for x in (await client.get("/roles", headers=admin_headers)).json()}
    try:
        await client.post("/users", json={
            "login": "ztest_heal", "password": "Xy345678", "role_ids": [roles["user"]]}, headers=admin_headers)
        tok = await login(client, "ztest_heal", "Xy345678")
        r = await client.post("/maintenance/heal", headers=hdr(tok))
        assert r.status_code == 403
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from user_roles where user_id in (select id from users where login='ztest_heal')")
            await conn.execute("delete from users where login='ztest_heal'")
