"""Регулярная проверка резервной копии восстановлением (11.10.2026).

Хостовой планировщик `restore-check-watch.sh` гоняется тестом САМ — в
копии каталога поставки с подставным `restore-check.sh`, который только
отмечает, что его запустили. Ошибки тут обе тихие: не запустит — копию так и
не проверят, запустит лишнее — временная база рядом с рабочей каждую минуту.

Серверная часть — итог проверки на экране и уведомление о провале или
просрочке, один раз на состояние.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_DEPLOY = Path("/deploy")
ROOT = _DEPLOY if (_DEPLOY / "restore-check-watch.sh").exists() else Path(__file__).resolve().parents[2]
WATCH = ROOT / "restore-check-watch.sh"
DAY = 86400


def _setup(tmp_path: Path, backup_age_days: float | None = 1) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    shutil.copy(WATCH, repo / "restore-check-watch.sh")
    stub = repo / "restore-check.sh"
    stub.write_text('#!/usr/bin/env bash\necho started >> "$OPS_TRIGGER_DIR/stub.ran"\n')
    stub.chmod(0o755)
    (repo / "ops").mkdir()
    if backup_age_days is not None:
        d = repo / "backups" / "20261010-020000"
        d.mkdir(parents=True)
        dump = d / "db.dump"
        dump.write_text("x")
        t = time.time() - backup_age_days * DAY
        os.utime(dump, (t, t))
    return repo


def _run(repo: Path, hour: str = "04", **env) -> bool:
    e = dict(os.environ, OPS_TRIGGER_DIR=str(repo / "ops"), BACKUP_DIR=str(repo / "backups"),
             RESTORE_CHECK_CUR_HOUR=hour)
    e.update({k: str(v) for k, v in env.items()})
    r = subprocess.run(["bash", str(repo / "restore-check-watch.sh")], cwd=str(repo), env=e,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr[:400]
    for _ in range(50):                 # проверка уходит в фон
        if (repo / "ops" / "stub.ran").exists():
            return True
        time.sleep(0.05)
    return False


def _old_result(repo: Path, days: float) -> None:
    res = repo / "ops" / "restore-check.result"
    res.write_text('{"ok":true,"status":"ok"}')
    t = time.time() - days * DAY
    os.utime(res, (t, t))


def test_first_check_runs_at_night_window(tmp_path):
    repo = _setup(tmp_path)
    assert _run(repo, hour="04"), "проверки ещё не было, а свежий бэкап есть — пора"


def test_not_outside_night_window(tmp_path):
    repo = _setup(tmp_path)
    assert not _run(repo, hour="13"), "днём временная база рядом с рабочей не нужна"


def test_not_more_often_than_monthly(tmp_path):
    repo = _setup(tmp_path)
    _old_result(repo, days=5)
    assert not _run(repo), "проверяли 5 дней назад — рано"


def test_monthly_check_after_30_days(tmp_path):
    repo = _setup(tmp_path, backup_age_days=1)
    _old_result(repo, days=31)
    assert _run(repo)


def test_same_backup_is_not_checked_twice(tmp_path):
    """Нового набора после прошлой проверки нет — проверять тот же второй раз незачем."""
    repo = _setup(tmp_path, backup_age_days=40)
    _old_result(repo, days=31)
    assert not _run(repo)


def test_request_runs_any_time_and_is_consumed(tmp_path):
    repo = _setup(tmp_path)
    _old_result(repo, days=1)
    (repo / "ops" / "restore-check.request").write_text("{}")
    assert _run(repo, hour="13"), "по кнопке — в любое время"
    assert not (repo / "ops" / "restore-check.request").exists()


def test_lock_and_maintenance_pause_block_start(tmp_path):
    repo = _setup(tmp_path)
    (repo / "ops" / "restore-check.request").write_text("{}")
    (repo / "ops" / "restore-check.lock").mkdir()
    assert not _run(repo), "идущую проверку второй экземпляр не трогает"
    (repo / "ops" / "restore-check.lock").rmdir()
    (repo / "ops" / "health-watch.off").write_text("")
    assert not _run(repo), "во время обновления не запускаем"


def test_failed_backup_set_does_not_count(tmp_path):
    repo = _setup(tmp_path)
    (repo / "backups" / "20261010-020000" / "FAILED.txt").write_text("сбой")
    assert not _run(repo), "проверять провалившийся набор бессмысленно"


def test_watcher_calls_planner_before_its_exit():
    text = (ROOT / "ops-trigger-watch.sh").read_text(encoding="utf-8")
    assert "restore-check-watch.sh" in text
    assert text.index("restore-check-watch.sh") < text.index('[ -f "$REQUEST" ] || exit 0'), \
        "планировщик стоит после выхода по отсутствию заявки на бэкап — не запустился бы никогда"


# ── Серверная часть ───────────────────────────────────────────────────────────

@pytest.fixture
def rc(tmp_path, monkeypatch):
    from app.modules.maintenance import restore_check_service as svc
    monkeypatch.setattr(svc, "TRIGGER_DIR", tmp_path)
    monkeypatch.setattr(svc, "RESULT_FILE", tmp_path / "restore-check.result")
    monkeypatch.setattr(svc, "REQUEST_FILE", tmp_path / "restore-check.request")
    monkeypatch.setattr(svc, "LOCK_DIR", tmp_path / "restore-check.lock")
    monkeypatch.setattr(svc, "NOTIFIED_FILE", tmp_path / "restore-check.notified")
    return svc


def _result(svc, status: str, days_ago: int) -> None:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    svc.RESULT_FILE.write_text(json.dumps({"ts": ts, "ok": status != "fail", "status": status,
                                           "message": "m", "set": "20261010-020000"}))


def test_status_states(rc):
    assert rc.status()["state"] == "never", "отсутствие проверки — не «всё хорошо»"
    _result(rc, "ok", 3)
    assert rc.status()["state"] == "ok"
    _result(rc, "diff", 3)
    assert rc.status()["state"] == "diff"
    _result(rc, "ok", 60)
    assert rc.status()["state"] == "overdue"
    _result(rc, "fail", 1)
    assert rc.status()["state"] == "fail"


def test_announce_once_per_state(rc):
    _result(rc, "ok", 2)
    assert rc.to_announce() is None, "о порядке не сообщаем"
    _result(rc, "fail", 1)
    news = rc.to_announce()
    assert news and news["state"] == "fail"
    rc.mark_announced(news["key"])
    assert rc.to_announce() is None, "одно сообщение на провал, не каждые 10 минут"
    _result(rc, "fail", 0)
    assert rc.to_announce() is not None, "новый провал — новое сообщение"


@pytest.mark.asyncio(loop_scope="session")
async def test_run_now_endpoint(client, admin_headers, rc):
    r = await client.get("/maintenance/restore-check", headers=admin_headers)
    assert r.status_code == 200 and r.json()["state"] == "never"
    r = await client.post("/maintenance/restore-check/run-now", headers=admin_headers)
    assert r.status_code == 200 and rc.REQUEST_FILE.exists()
    r = await client.post("/maintenance/restore-check/run-now", headers=admin_headers)
    assert r.status_code == 409, "вторая заявка, пока первая не подхвачена, — честный отказ"


@pytest.mark.asyncio(loop_scope="session")
async def test_failed_check_is_announced_once(rc):
    """Провал проверки доходит до управляющих уведомлением — один раз."""
    from app import db
    from app.modules.maintenance import service as maint

    _result(rc, "fail", 0)
    try:
        assert await maint.notify_restore_check() is True
        assert await maint.notify_restore_check() is False, "повтор того же провала молчит"
        async with db.acquire() as conn:
            n = await conn.fetchval(
                "select count(*) from notification_events where event_type='system.restore_check' "
                "and payload->>'state'='fail' and created_at > now() - interval '1 minute'")
        assert n >= 1
    finally:
        async with db.acquire() as conn:
            await conn.execute(
                "delete from notification_recipients where notification_event_id in "
                "(select id from notification_events where event_type='system.restore_check')")
            await conn.execute("delete from notification_events where event_type='system.restore_check'")


def test_worker_sees_trigger_dir():
    """Уведомление шлёт воркер — без каталога ops-triggers он итога не видит (11.10.2026)."""
    import yaml
    for name in ("docker-compose.prod.yml",):
        conf = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
        vols = conf["services"]["worker"].get("volumes") or []
        assert any(str(v).endswith(":/app/ops-triggers") for v in vols), name
