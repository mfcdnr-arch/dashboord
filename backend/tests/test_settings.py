"""Графические настройки-пороги (/system/settings) — фаза 2 (замена правки .env)."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import hdr, login  # noqa: E402
from app import db  # noqa: E402


async def test_get_settings_has_system_and_org_sections(client, admin_headers):
    r = await client.get("/system/settings", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("login_max_attempts", "login_lockout_minutes", "cpu_warn", "cpu_crit",
              "ram_warn", "ram_crit", "disk_warn", "disk_crit"):
        assert k in body["system"]
    for k in ("stale_days", "retention_months"):
        assert k in body["org"]


async def test_put_system_settings_roundtrip(client, admin_headers):
    r = await client.put("/system/settings/system", json={"cpu_warn": 60, "cpu_crit": 85}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["cpu_warn"] == 60
    assert r.json()["cpu_crit"] == 85

    r = await client.get("/system/settings", headers=admin_headers)
    assert r.json()["system"]["cpu_warn"] == 60
    assert r.json()["system"]["cpu_crit"] == 85

    # Влияет на реальный health-репорт (уровень порогов теперь берётся из настроек).
    r = await client.get("/reports/system", headers=admin_headers)
    assert r.status_code == 200

    # Восстановить дефолт, чтобы не влиять на другие тесты.
    r = await client.put("/system/settings/system", json={"cpu_warn": 70, "cpu_crit": 90}, headers=admin_headers)
    assert r.status_code == 200


async def test_put_system_settings_rejects_warn_gte_crit(client, admin_headers):
    r = await client.put("/system/settings/system", json={"cpu_warn": 95, "cpu_crit": 90}, headers=admin_headers)
    assert r.status_code == 422, r.text


async def test_put_system_settings_rejects_out_of_range(client, admin_headers):
    r = await client.put("/system/settings/system", json={"login_max_attempts": -1}, headers=admin_headers)
    assert r.status_code == 422, r.text


async def test_put_org_settings_roundtrip(client, admin_headers):
    r = await client.put("/system/settings/org", json={"stale_days": 30, "retention_months": 6}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["stale_days"] == 30
    assert r.json()["retention_months"] == 6

    r = await client.get("/system/settings", headers=admin_headers)
    assert r.json()["org"]["stale_days"] == 30
    assert r.json()["org"]["retention_months"] == 6

    # check_freshness/run_retention без явного параметра теперь используют это значение.
    r = await client.post("/maintenance/freshness/check", headers=admin_headers)
    assert r.status_code == 200

    # Восстановить дефолт.
    r = await client.put("/system/settings/org", json={"stale_days": 45, "retention_months": 12}, headers=admin_headers)
    assert r.status_code == 200


async def test_settings_forbidden_for_regular_user(client, admin_headers):
    roles = {x["code"]: x["id"] for x in (await client.get("/roles", headers=admin_headers)).json()}
    try:
        await client.post("/users", json={
            "login": "ztest_settings", "password": "Xy345678", "role_ids": [roles["user"]]}, headers=admin_headers)
        tok = await login(client, "ztest_settings", "Xy345678")
        r = await client.get("/system/settings", headers=hdr(tok))
        assert r.status_code == 403
        r = await client.put("/system/settings/system", json={"cpu_warn": 50}, headers=hdr(tok))
        assert r.status_code == 403
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from user_roles where user_id in (select id from users where login='ztest_settings')")
            await conn.execute("delete from users where login='ztest_settings'")
