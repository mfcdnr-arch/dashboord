"""Запрос доступа к отчёту, которого зритель не видит (п. 15, третья идея).

Главное здесь — то, чего в системе НЕТ и не должно появиться: списка
недоступных отчётов. Зритель видит только открытое ему, и это не техническое
ограничение, а суть — даже одни названия говорят, какие показатели за кем
закреплены. Поэтому запрос идёт от человека словами, а ценность в другом: он
уходит одним нажатием и приходит с именем автора, так что администратору
остаётся открыть карточку доступа и отметить галочку.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db


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


async def _drop(did):
    async with db.acquire() as conn:
        await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
        await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
        await conn.execute("delete from audit_log where entity_id=$1::uuid", did)
        await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_access_request_reaches_admin_with_author(client, admin_headers, viewer):
    try:
        r = await client.post("/appeals/access-request", headers=viewer["headers"],
                              json={"wanted": "Еженедельный доклад, о нём говорили на планёрке"})
        assert r.status_code == 201, r.text
        aid = r.json()["id"]

        d = (await client.get(f"/appeals/{aid}", headers=admin_headers)).json()
        assert d["context"]["kind"] == "access_request"
        # id автора — то, ради чего контекст и нужен: администратор открывает
        # карточку доступа именно этого сотрудника, а не ищет его в списке.
        assert d["author_id"] == viewer["id"]
        assert "планёрке" in d["messages"][0]["body"]
        assert d["subject"] == "Запрос доступа к отчёту"

        # Карточка доступа этого сотрудника действительно открывается и содержит
        # дашборды организации — выдача сводится к галочке.
        acc = await client.get(f"/users/{viewer['id']}/dashboard-access", headers=admin_headers)
        assert acc.status_code == 200, acc.text
        assert "items" in acc.json()
    finally:
        await _purge(viewer["id"])


async def test_access_request_needs_text_and_does_not_leak_dashboards(client, admin_headers, viewer):
    """Пустой запрос отклоняется; чужие отчёты зрителю по-прежнему не видны."""
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ЗАКРЫТЫЙ отчёт"})).json()["id"]
    try:
        r = await client.post("/appeals/access-request", headers=viewer["headers"], json={"wanted": "   "})
        assert r.status_code in (400, 422), r.text

        # Ни в списке, ни поштучно — запрос доступа ничего не открывает сам по себе.
        lst = (await client.get("/dashboards", headers=viewer["headers"])).json()
        assert all("ЗАКРЫТЫЙ" not in i["name"] for i in lst["items"])
        assert (await client.get(f"/dashboards/{did}", headers=viewer["headers"])).status_code == 404
    finally:
        await _purge(viewer["id"])
        await _drop(did)
