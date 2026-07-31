"""Статус бэкапа + «Запустить сейчас» (/maintenance/backup/*) и ручной запуск
автоархива (/maintenance/archive/*) — фаза 2в (графическое управление вместо
голого CLI backup.sh/backup-schedule.sh)."""
import json

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import hdr, login  # noqa: E402
from app import db  # noqa: E402
from app.modules.maintenance import backup_service  # noqa: E402


@pytest.fixture
def tmp_ops_dirs(tmp_path, monkeypatch):
    """Подменяет пути backup_service на временный каталог — тесты не должны
    трогать реальный /app/backups (на хосте pytest его вообще нет)."""
    backups = tmp_path / "backups"
    triggers = tmp_path / "ops-triggers"
    monkeypatch.setattr(backup_service, "BACKUPS_DIR", backups)
    monkeypatch.setattr(backup_service, "TRIGGER_DIR", triggers)
    monkeypatch.setattr(backup_service, "TRIGGER_FILE", triggers / "backup.request")
    monkeypatch.setattr(backup_service, "RESULT_FILE", triggers / "backup.result")
    return backups, triggers


async def test_backup_status_empty_when_nothing_yet(client, admin_headers, tmp_ops_dirs):
    r = await client.get("/maintenance/backup/status", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sets"] == []
    assert body["pending"] is False
    assert body["last_manual_result"] is None


async def test_backup_run_now_creates_trigger_and_blocks_duplicate(client, admin_headers, tmp_ops_dirs):
    _, triggers = tmp_ops_dirs
    r = await client.post("/maintenance/backup/run-now", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["requested"] is True
    assert (triggers / "backup.request").exists()

    r2 = await client.post("/maintenance/backup/run-now", headers=admin_headers)
    assert r2.status_code == 409, r2.text


async def test_backup_status_lists_sets_and_last_result(client, admin_headers, tmp_ops_dirs):
    backups, triggers = tmp_ops_dirs
    d = backups / "20260101-000000"
    d.mkdir(parents=True)
    (d / "db.dump").write_bytes(b"x" * 100)
    triggers.mkdir(parents=True, exist_ok=True)
    (triggers / "backup.result").write_text(json.dumps({"ts": "now", "ok": True, "message": "ok"}))

    r = await client.get("/maintenance/backup/status", headers=admin_headers)
    body = r.json()
    assert body["sets"][0]["name"] == "20260101-000000"
    assert body["sets"][0]["db_dump_bytes"] == 100
    assert body["sets"][0]["minio_tgz_bytes"] is None
    assert body["last_manual_result"]["ok"] is True


async def test_backup_forbidden_for_regular_user(client, admin_headers, tmp_ops_dirs):
    roles = {x["code"]: x["id"] for x in (await client.get("/roles", headers=admin_headers)).json()}
    try:
        await client.post("/users", json={
            "login": "ztest_backup", "password": "Xy345678", "role_ids": [roles["user"]]}, headers=admin_headers)
        tok = await login(client, "ztest_backup", "Xy345678")
        r = await client.get("/maintenance/backup/status", headers=hdr(tok))
        assert r.status_code == 403
        r2 = await client.post("/maintenance/backup/run-now", headers=hdr(tok))
        assert r2.status_code == 403
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from user_roles where user_id in (select id from users where login='ztest_backup')")
            await conn.execute("delete from users where login='ztest_backup'")


async def test_archive_run_now_is_idempotent_and_status_updates(client, admin_headers):
    r1 = await client.post("/maintenance/archive/run-now", headers=admin_headers)
    assert r1.status_code == 200, r1.text
    n1 = r1.json()["archived"]

    # Повторный запуск в том же месяце не должен создавать новые слепки (идемпотентно).
    r2 = await client.post("/maintenance/archive/run-now", headers=admin_headers)
    assert r2.status_code == 200
    assert r2.json()["archived"] == 0

    r3 = await client.get("/maintenance/archive/status", headers=admin_headers)
    assert r3.status_code == 200
    body = r3.json()
    assert "last_run" in body and "recent_count" in body
    if n1 > 0:
        assert body["last_run"] is not None
