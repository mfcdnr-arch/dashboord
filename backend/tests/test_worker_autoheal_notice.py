"""Автоперезапуск воркера не должен быть молчаливым.

Хостовой сторож (worker-guard.sh) поднимает упавший воркер и пишет запись в
`system_heal_log`. Экран «История починок» её покажет, но экран надо открыть —
а «само починилось» без единого сигнала скроет от заказчика, что воркер падает
ежедневно. Уведомление рассылает сторожевой cron уже ПОСЛЕ оживления воркера:
пока тот мёртв, рассылать некому, и это честнее, чем делать вид, что канал
есть.
"""
from __future__ import annotations

import json

import pytest_asyncio

from app import db
from app.modules.maintenance import service as maint

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _add_heal(status_before: str, status_after: str, healthy: bool, triggered_by: str = "auto") -> str:
    async with db.acquire() as conn:
        return str(await conn.fetchval(
            "insert into system_heal_log(triggered_by, status_before, status_after, healthy, actions) "
            "values($1,$2,$3,$4,$5::jsonb) returning id",
            triggered_by, status_before, status_after, healthy,
            json.dumps([{"name": "Фоновый воркер: перезапуск", "ok": healthy, "result": "тест"}])))


async def _drop_heal(hid: str) -> None:
    async with db.acquire() as conn:
        await conn.execute(
            "delete from notification_recipients where notification_event_id in "
            "(select id from notification_events where event_type='system.worker_restarted')")
        await conn.execute("delete from notification_events where event_type='system.worker_restarted'")
        await conn.execute("delete from system_heal_log where id=$1::uuid", hid)


async def _notices(heal_id: str | None = None) -> int:
    """Сколько уведомлений о перезапуске. С heal_id — только о ЭТОЙ починке.

    Считать все такие события нельзя: на стенде живут и посторонние (например,
    от живой проверки на самом стеке), и тест падал бы из-за чужой записи,
    ничего не говоря о своём предмете.
    """
    async with db.acquire() as conn:
        if heal_id:
            return await conn.fetchval(
                "select count(*) from notification_events "
                "where event_type='system.worker_restarted' and entity_id=$1::uuid", heal_id)
        return await conn.fetchval(
            "select count(*) from notification_events where event_type='system.worker_restarted'")


@pytest_asyncio.fixture
async def clean_notices():
    yield
    async with db.acquire() as conn:
        await conn.execute(
            "delete from notification_recipients where notification_event_id in "
            "(select id from notification_events where event_type='system.worker_restarted')")
        await conn.execute("delete from notification_events where event_type='system.worker_restarted'")


async def test_perezapusk_uvedomlyaet_i_ne_dublirue(ids, clean_notices):
    """Первое обращение шлёт уведомление, повторное — нет.

    Сторож крутится каждые 10 минут; без отметки «уже сообщили» одно падение
    воркера рассылалось бы бесконечно и приучило бы не читать колокольчик.
    """
    hid = await _add_heal("worker_down", "worker_ok", True)
    try:
        sent = await maint.notify_worker_restarts()
        assert sent >= 1, "о перезапуске не уведомили"
        assert await _notices(hid) == 1, "уведомление о нашей починке не создано"

        again = await maint.notify_worker_restarts()
        assert again == 0, "повторная рассылка о том же перезапуске"
        assert await _notices(hid) == 1, "уведомление продублировано"

        async with db.acquire() as conn:
            notified = await conn.fetchval("select notified_at from system_heal_log where id=$1::uuid", hid)
        assert notified is not None, "отметка об уведомлении не проставлена"
    finally:
        await _drop_heal(hid)


async def test_obychnaya_avtopochinka_ne_shlet_eto_uvedomlenie(ids, clean_notices):
    """🔴 Сторож пишет запись при КАЖДОМ degraded — каждые 10 минут.

    Уведомляй мы обо всех авто-починках, колокольчик заполнился бы за час.
    Признак перезапуска воркера — `worker_down` в статусе «до», его ставит
    только хостовой сторож.
    """
    hid = await _add_heal("degraded", "ok", True)
    try:
        sent = await maint.notify_worker_restarts()
        assert sent == 0, "обычная автопочинка не должна слать уведомление о перезапуске воркера"
        assert await _notices(hid) == 0
    finally:
        await _drop_heal(hid)


async def test_neudachnyy_perezapusk_tozhe_soobschaetsya(ids, clean_notices):
    """Воркер перезапущен, но так и не отметился — молчать тем более нельзя."""
    hid = await _add_heal("worker_down", "worker_down", False)
    try:
        assert await maint.notify_worker_restarts() >= 1
        async with db.acquire() as conn:
            payload = await conn.fetchval(
                "select payload from notification_events "
                "where event_type='system.worker_restarted' and entity_id=$1::uuid", hid)
        p = json.loads(payload) if isinstance(payload, str) else payload
        assert p["healthy"] is False, f"в уведомлении не сказано, что перезапуск не помог: {p}"
    finally:
        await _drop_heal(hid)


@pytest.mark.asyncio(loop_scope="session")
async def test_rassylka_stoit_do_vykhoda_po_zdorovomu_statusu():
    """🔴 Регрессия на порядок в сторожевом cron.

    После удачного перезапуска система снова «ok», и сторож выходит по раннему
    `return`. Встань рассылка после него — уведомление не ушло бы никогда, то
    есть воркер чинился бы молча: ровно то поведение, против которого вся эта
    работа.
    """
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "app" / "modules" / "ingestion" / "worker.py"
    text = src.read_text()
    body = text[text.index("async def system_watchdog"):]
    notify_pos = body.index("notify_worker_restarts")
    return_pos = body.index('if health["status"] != "degraded"')
    assert notify_pos < return_pos, "рассылка о перезапусках стоит ПОСЛЕ выхода по здоровому статусу"
