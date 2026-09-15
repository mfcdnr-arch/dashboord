"""Управление сторожем воркера с экрана: состояние, пауза, сброс, потолок.

Сторож живёт на хосте, но управлять им человек должен мышью, а не файлами по
ssh — иначе плановое обслуживание требует консоли, а исчерпанный потолок
снимается только ожиданием часа.

Отдельная забота — самонаблюдение: сторож обязан отмечать, что он вообще
запускался. Остановись его таймер, и автоматика перестала бы работать молча —
ровно тот класс дефекта, против которого она и заведена.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app import db
from app.modules.maintenance import worker_guard_service as wg
from app.modules.system import settings_service as sset

pytestmark = pytest.mark.asyncio(loop_scope="session")

TRIG = Path(os.environ.get("OPS_TRIGGER_DIR", "/app/ops-triggers"))


def _clean() -> None:
    for n in ("worker.result", "worker-guard.alive", "worker-autorestart.off", "worker-restarts.log"):
        f = TRIG / n
        if f.exists():
            f.unlink()


@pytest.fixture(autouse=True)
def clean_files():
    TRIG.mkdir(parents=True, exist_ok=True)
    _clean()
    yield
    _clean()


async def test_storozh_ni_razu_ne_otmechalsya_govorit_ob_etom_pryamo():
    """🔴 Отсутствие отметки и «всё хорошо» — разные вещи.

    На свежей установке таймер сторожа мог быть не зарегистрирован вовсе
    (`backup-schedule.sh install` не выполняли). Молчать об этом нельзя:
    автоперезапуска нет, а выглядит всё как обычно.
    """
    st = wg.status()
    assert st["watcher"] == "never", st
    assert "install" in (st.get("watcher_hint") or "").lower()


async def test_svezhaya_otmetka_znachit_storozh_rabotaet():
    (TRIG / "worker-guard.alive").write_text(str(int(time.time())))
    st = wg.status()
    assert st["watcher"] == "ok", st
    assert st["watcher_seen_at"]


async def test_staraya_otmetka_znachit_storozh_molchit():
    """Сторож запускается раз в минуту; час молчания — это отказ."""
    (TRIG / "worker-guard.alive").write_text(str(int(time.time()) - 7200))
    st = wg.status()
    assert st["watcher"] == "stale", st


async def test_bitaya_otmetka_ne_ronyaet_ekran():
    (TRIG / "worker-guard.alive").write_text("не число")
    st = wg.status()
    assert st["watcher"] in ("never", "stale"), st


async def test_pauza_stavitsya_i_snimaetsya_s_ekrana():
    """Плановое обслуживание без похода в консоль."""
    wg.set_paused(True, "admin")
    st = wg.status()
    assert st["paused"] is True
    assert "admin" in (st.get("paused_by") or ""), st

    wg.set_paused(False, "admin")
    assert wg.status()["paused"] is False
    assert not (TRIG / "worker-autorestart.off").exists()


async def test_sbros_schetchika_daet_popytki_zanovo():
    """Причину починили — ждать час незачем."""
    now = int(time.time())
    (TRIG / "worker-restarts.log").write_text(f"{now-100}\n{now-80}\n{now-60}\n")
    assert wg.status()["attempts_last_hour"] == 3

    removed = wg.reset_attempts("admin")
    assert removed == 3, "счётчик не сброшен"
    assert wg.status()["attempts_last_hour"] == 0


async def test_starye_popytki_ne_schitayutsya():
    """Окно — час: вчерашние падения сегодняшний потолок не выбирают."""
    now = int(time.time())
    (TRIG / "worker-restarts.log").write_text(f"{now-7200}\n{now-100}\n")
    assert wg.status()["attempts_last_hour"] == 1


async def test_potolok_beretsya_iz_nastroek():
    """Потолок правится мышью в «Настройках», а не в коде скрипта."""
    async with db.acquire() as conn:
        cur = await sset.get_system_settings(conn)
        assert "worker_restart_max_per_hour" in cur, "потолка нет среди системных настроек"
        try:
            upd = await sset.update_system_settings(conn, None, {"worker_restart_max_per_hour": 5})
            assert upd["worker_restart_max_per_hour"] == 5
            again = await sset.get_system_settings(conn)
            assert again["worker_restart_max_per_hour"] == 5, "значение не сохранилось"
        finally:
            await sset.update_system_settings(
                conn, None, {"worker_restart_max_per_hour": cur["worker_restart_max_per_hour"]})


# --- Через HTTP: то, чем человек пользуется с экрана ---

async def test_pauza_i_sbros_dostupny_s_ekrana(client, admin_headers):
    """Управление сторожем — мышью, а не файлами по ssh."""
    r = await client.get("/maintenance/worker-guard", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["paused"] is False

    r = await client.post("/maintenance/worker-guard/pause", json={"paused": True}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert (await client.get("/maintenance/worker-guard", headers=admin_headers)).json()["paused"] is True

    r = await client.post("/maintenance/worker-guard/pause", json={"paused": False}, headers=admin_headers)
    assert r.status_code == 200
    assert (await client.get("/maintenance/worker-guard", headers=admin_headers)).json()["paused"] is False

    import time as _t
    (TRIG / "worker-restarts.log").write_text(f"{int(_t.time())}\n")
    r = await client.post("/maintenance/worker-guard/reset", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["cleared"] == 1
    assert (await client.get("/maintenance/worker-guard", headers=admin_headers)).json()["attempts_last_hour"] == 0


async def test_zritelyu_upravlenie_zakryto(client, viewer):
    """Пауза автоматики — операция эксплуатации, не для зрителя."""
    r = await client.post("/maintenance/worker-guard/pause", json={"paused": True}, headers=viewer["headers"])
    assert r.status_code == 403, r.text
    assert not (TRIG / "worker-autorestart.off").exists()


async def test_sostoyanie_storozha_prihodit_so_strokoy_vorkera():
    """Самонаблюдение видно там же, где сам воркер, а не в отдельном углу."""
    from app.modules.reports import service as reports_svc
    (TRIG / "worker-guard.alive").write_text(str(int(time.time()) - 7200))
    async with db.acquire() as conn:
        health = await reports_svc.system_health(conn)
    worker = next(s for s in health["services"] if s["name"] == "Фоновый воркер")
    assert worker.get("guard"), "состояние сторожа не показано рядом с воркером"
    assert worker["guard"]["watcher"] == "stale"
