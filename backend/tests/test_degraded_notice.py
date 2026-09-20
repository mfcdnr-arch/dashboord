"""Плохое состояние системы не остаётся без сигнала (20.09.2026).

Сторож уведомлял управляющих по условию `if not result["healthy"]`, но
`healthy` означает «удались ли ДЕЙСТВИЯ починки», а действий всего два:
создать бакет MinIO и проверить связь с Redis. Переполненный диск, забитая
память и упёршийся CPU тоже дают degraded — и оба действия при этом проходят
успешно, `healthy` выходит True, уведомление не уходит, не узнаёт никто.

Теперь сигнал зависит от СОСТОЯНИЯ системы после починки, а не от успеха
самой починки, и называет причину словами.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.maintenance import service as maint


async def test_reasons_name_what_is_wrong():
    """Причина названа словами: ресурсы и упавшие сервисы."""
    health = {
        "status": "degraded",
        "services": [{"name": "PostgreSQL", "ok": True}, {"name": "MinIO", "ok": False}],
        "disk": {"percent": 97.4, "level": "danger"},
        "memory": {"percent": 61.0, "level": "ok"},
        "cpu": {"percent": 99.0, "level": "danger"},
    }
    reasons = await maint.degraded_reasons(health)
    assert any("MinIO" in r for r in reasons), "упавший сервис не назван"
    assert any("диск" in r and "97.4" in r for r in reasons), "переполненный диск не назван"
    assert any("процессор" in r for r in reasons)
    assert not any("память" in r for r in reasons), "нормальный ресурс попал в список проблем"


async def test_healthy_system_has_no_reasons():
    """Обратная сторона: на здоровой системе список пуст."""
    ok = {"status": "ok", "services": [{"name": "PostgreSQL", "ok": True}],
          "disk": {"percent": 30, "level": "ok"}, "memory": {"percent": 40, "level": "ok"},
          "cpu": {"percent": 5, "level": "ok"}}
    assert await maint.degraded_reasons(ok) == []


async def test_notice_goes_out_even_when_heal_reported_success(ids):
    """🔴 Главное: починка сказала «здоров», а система — нет. Сигнал обязан уйти."""
    org = ids["org"]
    async with db.acquire() as conn:
        await conn.execute("delete from notification_recipients where notification_event_id in "
                           "(select id from notification_events where organization_id=$1 "
                           " and event_type='system.degraded')", org)
        await conn.execute("delete from notification_events where organization_id=$1 "
                           "and event_type='system.degraded'", org)
        # Ровно тот случай: действия удались (healthy=True), состояние плохое.
        await maint.notify_degraded(conn, org, {
            "actions": [{"name": "MinIO: бакет документов", "ok": True, "result": "уже был"},
                        {"name": "Redis: связь", "ok": True, "result": "доступен"}],
            "healthy": True,
            "status_after": "degraded",
        })
        ev = await conn.fetchrow(
            "select payload from notification_events where organization_id=$1 "
            "and event_type='system.degraded' order by created_at desc limit 1", org)
        assert ev is not None, "🔴 система в плохом состоянии, а сигнала нет"
        import json
        payload = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
        assert payload["status_after"] == "degraded"
        assert "reasons" in payload, "в уведомлении не сказано, что именно не так"

        # Антидубль сохранён: сторож ходит каждые 10 минут.
        await maint.notify_degraded(conn, org, {"actions": [], "healthy": True,
                                                "status_after": "degraded"})
        cnt = await conn.fetchval(
            "select count(*) from notification_events where organization_id=$1 "
            "and event_type='system.degraded'", org)
        assert cnt == 1, "антидубль сломан — колокольчик заполнится за час"

        await conn.execute("delete from notification_recipients where notification_event_id in "
                           "(select id from notification_events where organization_id=$1 "
                           " and event_type='system.degraded')", org)
        await conn.execute("delete from notification_events where organization_id=$1 "
                           "and event_type='system.degraded'", org)


def test_watchdog_reacts_to_state_not_to_heal_result():
    """Страж: условие в стороже смотрит на состояние, а не на успех починки.

    Возврат `if not result["healthy"]` — правка одного слова, и система снова
    замолчит при переполненном диске."""
    import inspect

    from app.modules.ingestion import worker

    src = inspect.getsource(worker.system_watchdog)
    assert 'result["status_after"] == "degraded"' in src, \
        "сторож снова уведомляет по успеху починки, а не по состоянию системы"
    assert 'if not result["healthy"]' not in src
