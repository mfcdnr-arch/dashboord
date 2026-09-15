"""Итог работы сторожа виден на экране «Здоровье системы».

Зачем отдельный канал помимо уведомлений. Уведомление рассылает сторожевой
cron — то есть сам воркер; когда он так и не поднялся, рассылать некому.
Именно этот случай самый важный: система молчит, а конвейер стоит. Поэтому
сторож пишет результат файлом на общий том, а API его читает — путь, не
зависящий ни от живого воркера, ни от Redis.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.modules.maintenance import worker_guard_service

pytestmark = pytest.mark.asyncio(loop_scope="session")

TRIG = Path(os.environ.get("OPS_TRIGGER_DIR", "/app/ops-triggers"))


def _write(payload: dict) -> None:
    TRIG.mkdir(parents=True, exist_ok=True)
    (TRIG / "worker.result").write_text(json.dumps(payload, ensure_ascii=False))


def _clear() -> None:
    f = TRIG / "worker.result"
    if f.exists():
        f.unlink()


async def test_priostanovka_vidna_na_ekrane():
    """Потолок попыток исчерпан — человек обязан узнать об этом с экрана."""
    try:
        _write({"ts": "2026-09-15T10:00:00Z", "state": "suspended", "ok": False,
                "message": "Автоперезапуск приостановлен: 3 попытки за час не помогли"})
        st = worker_guard_service.last_result()
        assert st is not None, "итог работы сторожа не доехал до API"
        assert st["state"] == "suspended"
        assert "приостанов" in st["message"].lower()
    finally:
        _clear()


async def test_bez_fayla_nichego_ne_vydumyvaem():
    """Сторож ещё не срабатывал — это не повод показывать что-либо."""
    _clear()
    assert worker_guard_service.last_result() is None


async def test_bitiy_fayl_ne_ronyaet_ekran():
    """Файл мог оборваться на записи. Экран здоровья важнее его содержимого."""
    try:
        TRIG.mkdir(parents=True, exist_ok=True)
        (TRIG / "worker.result").write_text("{битый")
        assert worker_guard_service.last_result() is None
    finally:
        _clear()


async def test_itog_storozha_prihodit_so_strokoy_vorkera():
    """Сведения должны стоять рядом с воркером, а не в отдельном углу экрана."""
    from app import db
    from app.modules.reports import service as reports_svc
    try:
        _write({"ts": "2026-09-15T10:00:00Z", "state": "worker_ok", "ok": True,
                "message": "Воркер не отмечался и был перезапущен автоматически"})
        async with db.acquire() as conn:
            health = await reports_svc.system_health(conn)
        worker = next(s for s in health["services"] if s["name"] == "Фоновый воркер")
        assert worker.get("autorestart"), "итог сторожа не показан рядом с воркером"
        assert worker["autorestart"]["state"] == "worker_ok"
    finally:
        _clear()
