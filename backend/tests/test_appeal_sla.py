"""Доработки обратной связи по итогам ревью п. 15.

Три вещи, каждая закрывает свой перекос:

  • **потолок новых обращений** — кнопка «⚑ проблема» на виджете сделала
    достижимым то, что раньше было теоретическим: обойти страницу и завести
    два десятка обращений подряд. Ограничиваются только НОВЫЕ обращения:
    замолчать человека посреди уже начатого разговора нельзя;
  • **срок ответа** — сам по себе ничего не запрещает, он делает ожидание
    видимым: без него очередь выглядит одинаково и на первом часу, и на
    третьи сутки;
  • **отметка о первом просмотре** — до первого ответа обращение выглядит для
    автора так же, как в момент отправки, то есть как будто ушло в пустоту.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.appeals.service import MAX_NEW_APPEALS_PER_HOUR


async def _purge(user_id):
    async with db.acquire() as conn:
        ids = [r["id"] for r in await conn.fetch("select id from appeals where user_id=$1", user_id)]
        for aid in ids:
            await conn.execute("delete from appeal_messages where appeal_id=$1", aid)
            await conn.execute("delete from audit_log where entity_id=$1", aid)
            await conn.execute("delete from notification_recipients where notification_event_id in "
                               "(select id from notification_events where entity_id=$1)", aid)
            await conn.execute("delete from notification_events where entity_id=$1", aid)
        await conn.execute("delete from appeals where user_id=$1", user_id)


async def test_rate_limit_counts_only_new_appeals(client, viewer):
    """Потолок бьёт по новым обращениям и НЕ мешает переписке в открытом."""
    try:
        first_id = None
        for i in range(MAX_NEW_APPEALS_PER_HOUR):
            r = await client.post("/appeals", headers=viewer["headers"],
                                  json={"subject": f"ztest {i}", "body": "проверка потолка"})
            assert r.status_code == 201, r.text
            if first_id is None:
                first_id = r.json()["id"]

        # Следующее — отказ 429 (не 400: это не ошибка ввода, а просьба подождать)
        r = await client.post("/appeals", headers=viewer["headers"],
                              json={"subject": "ztest лишнее", "body": "ещё одно"})
        assert r.status_code == 429, r.text
        # Отказ называет, когда можно продолжить, иначе читается как поломка.
        assert "мин" in r.json()["detail"]

        # А дописать в уже открытое обращение по-прежнему можно: очередь
        # администратора от этого не растёт.
        r = await client.post(f"/appeals/{first_id}/messages", headers=viewer["headers"],
                              json={"body": "уточнение к первому"})
        assert r.status_code == 201, r.text
    finally:
        await _purge(viewer["id"])


async def test_first_view_by_staff_is_recorded_and_notified(client, admin_headers, viewer):
    """Автор видит, что жалобу заметили, ещё до ответа."""
    try:
        aid = (await client.post("/appeals", headers=viewer["headers"],
                                 json={"subject": "ztest просмотр", "body": "посмотрите"})).json()["id"]

        # Пока никто из администрации не открывал — отметки нет.
        mine = (await client.get("/appeals/mine", headers=viewer["headers"])).json()["items"]
        row = next(i for i in mine if i["id"] == aid)
        assert row["first_seen_at"] is None
        assert row["waiting_hours"] is not None and row["waiting_hours"] >= 0

        # Собственный просмотр автора отметку НЕ ставит — иначе она означала бы
        # «я сам на себя посмотрел».
        await client.get(f"/appeals/{aid}", headers=viewer["headers"])
        assert (await client.get(f"/appeals/{aid}", headers=viewer["headers"])).json()["first_seen_at"] is None

        # Открыл администратор — отметка появилась и автору ушло уведомление.
        d = (await client.get(f"/appeals/{aid}", headers=admin_headers)).json()
        assert d["first_seen_at"] is not None and d["first_seen_by"]
        async with db.acquire() as conn:
            seen = await conn.fetchval(
                "select count(*) from notification_events where entity_id=$1::uuid and event_type='appeal.seen'", aid)
        assert seen == 1

        # Повторный просмотр не переставляет отметку и не шлёт второе
        # уведомление: сообщать о каждом открытии карточки — это шум.
        first_at = d["first_seen_at"]
        again = (await client.get(f"/appeals/{aid}", headers=admin_headers)).json()
        assert again["first_seen_at"] == first_at
        async with db.acquire() as conn:
            seen = await conn.fetchval(
                "select count(*) from notification_events where entity_id=$1::uuid and event_type='appeal.seen'", aid)
        assert seen == 1
    finally:
        await _purge(viewer["id"])


async def test_waiting_only_for_open_and_response_hours_exposed(client, admin_headers, viewer):
    """«Ждёт N» считается только у открытых; срок ответа приходит со списком."""
    try:
        aid = (await client.post("/appeals", headers=viewer["headers"],
                                 json={"subject": "ztest срок", "body": "вопрос"})).json()["id"]

        lst = (await client.get("/appeals", headers=admin_headers)).json()
        assert lst["response_hours"] >= 1  # срок задаётся в «Настройках», умолчание — сутки
        row = next(i for i in lst["items"] if i["id"] == aid)
        assert row["waiting_hours"] is not None

        # Ответили — ожидание кончилось, растущая цифра рядом означала бы
        # несуществующую проблему.
        await client.post(f"/appeals/{aid}/messages", headers=admin_headers, json={"body": "ответ"})
        lst = (await client.get("/appeals", headers=admin_headers)).json()
        row = next(i for i in lst["items"] if i["id"] == aid)
        assert row["status"] == "answered" and row["waiting_hours"] is None
    finally:
        await _purge(viewer["id"])
