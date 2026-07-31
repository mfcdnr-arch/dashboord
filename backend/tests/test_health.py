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


async def test_heal_history_records_manual_call(client, admin_headers):
    """POST /maintenance/heal должен появляться в GET /maintenance/heal-history
    с triggered_by='manual' и статусами до/после (закрытие контура самодиагностики)."""
    r = await client.post("/maintenance/heal", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert "status_before" in r.json() and "status_after" in r.json()

    r = await client.get("/maintenance/heal-history", headers=admin_headers)
    assert r.status_code == 200, r.text
    hist = r.json()
    assert len(hist) >= 1
    latest = hist[0]
    assert latest["triggered_by"] == "manual"
    assert latest["triggered_by_login"] is not None
    assert isinstance(latest["actions"], list)


async def test_heal_history_forbidden_for_regular_user(client, admin_headers):
    roles = {x["code"]: x["id"] for x in (await client.get("/roles", headers=admin_headers)).json()}
    try:
        await client.post("/users", json={
            "login": "ztest_heal2", "password": "Xy345678", "role_ids": [roles["user"]]}, headers=admin_headers)
        tok = await login(client, "ztest_heal2", "Xy345678")
        r = await client.get("/maintenance/heal-history", headers=hdr(tok))
        assert r.status_code == 403
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from user_roles where user_id in (select id from users where login='ztest_heal2')")
            await conn.execute("delete from users where login='ztest_heal2'")


async def test_system_watchdog_auto_heals_when_degraded(monkeypatch):
    """Сторожевой arq-cron (worker.system_watchdog): при status=='degraded' сам
    вызывает heal_and_log('auto') и, если после починки всё ещё плохо — уведомляет
    admin/moderator организации. Тестируем без реальной деградации — подменяем
    system_health, чтобы не зависеть от текущей нагрузки CI-раннера."""
    from app.modules.ingestion import worker
    from app.modules.maintenance import service as maint

    calls = {"heal": 0, "notify": 0}

    async def fake_health(conn):
        return {"status": "degraded"}

    async def fake_heal_and_log(conn, triggered_by, user_id=None, user_org_id=None):
        calls["heal"] += 1
        assert triggered_by == "auto"
        return {"healthy": False, "actions": [], "status_before": "degraded", "status_after": "degraded"}

    async def fake_notify_degraded(conn, org_id, heal_result):
        calls["notify"] += 1

    monkeypatch.setattr(worker.reports_svc, "system_health", fake_health)
    monkeypatch.setattr(worker.maint, "heal_and_log", fake_heal_and_log)
    monkeypatch.setattr(worker.maint, "notify_degraded", fake_notify_degraded)

    await worker.system_watchdog({})

    assert calls["heal"] == 1
    assert calls["notify"] >= 1  # хотя бы одна организация в тестовой БД


async def test_system_watchdog_noop_when_healthy(monkeypatch):
    """Если система в норме — watchdog не должен трогать heal()/уведомления."""
    from app.modules.ingestion import worker

    async def fake_health(conn):
        return {"status": "ok"}

    called = {"heal": False}

    async def fake_heal_and_log(*a, **kw):
        called["heal"] = True

    monkeypatch.setattr(worker.reports_svc, "system_health", fake_health)
    monkeypatch.setattr(worker.maint, "heal_and_log", fake_heal_and_log)

    await worker.system_watchdog({})

    assert called["heal"] is False


async def test_notify_degraded_dedup_within_hour():
    """Антидубль: второй вызов notify_degraded для той же организации в течение
    часа не должен создавать второе событие (иначе watchdog каждые 10 мин спамил бы)."""
    from app.modules.maintenance import service as maint

    async with db.acquire() as conn:
        org_id = await conn.fetchval("select id from organizations limit 1")
        try:
            before = await conn.fetchval(
                "select count(*) from notification_events where organization_id=$1 and event_type='system.degraded'",
                org_id)
            await maint.notify_degraded(conn, org_id, {"actions": [], "status_after": "degraded"})
            await maint.notify_degraded(conn, org_id, {"actions": [], "status_after": "degraded"})
            after = await conn.fetchval(
                "select count(*) from notification_events where organization_id=$1 and event_type='system.degraded'",
                org_id)
            assert after == before + 1
        finally:
            await conn.execute(
                "delete from notification_events where organization_id=$1 and event_type='system.degraded'", org_id)
