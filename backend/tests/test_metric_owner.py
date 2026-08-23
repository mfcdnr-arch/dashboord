"""Владелец показателя (п. 11 списка предложений).

Поле `metrics.owner_id` лежало в БД с самого начала и не показывалось в
интерфейсе нигде, хотя по ТЗ у каждого KPI должен быть ответственный. Здесь
проверяется, что он не просто хранится, а РАБОТАЕТ: виден в подсказке ⓘ и в
разборе показателя, а жалоба «⚑ проблема» адресуется ему, не отменяя общую
очередь.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from conftest import purge_dashboard


async def _metric_with_owner(client, headers, code, owner_id=None):
    m = (await client.post("/metrics", headers=headers, json={
        "code": code, "name": f"Показатель {code}",
        **({"owner_id": owner_id} if owner_id else {})})).json()
    await client.post(f"/metrics/{m['id']}/versions", headers=headers,
                      json={"formula": "1 + 1", "unit": "шт"})
    return m


async def test_owner_is_set_shown_and_can_be_cleared(client, admin_headers, viewer):
    """Назначили — видно в списке и карточке; сняли — снова «не назначен»."""
    m = await _metric_with_owner(client, admin_headers, "ztest_owner_a")
    try:
        card = (await client.get(f"/metrics/{m['id']}", headers=admin_headers)).json()["metric"]
        assert card["owner_id"] is None and card["owner_name"] is None

        r = await client.patch(f"/metrics/{m['id']}", headers=admin_headers,
                               json={"owner_id": viewer["id"]})
        assert r.status_code == 200, r.text
        card = (await client.get(f"/metrics/{m['id']}", headers=admin_headers)).json()["metric"]
        assert str(card["owner_id"]) == viewer["id"] and card["owner_name"]
        lst = (await client.get("/metrics?q=ztest_owner_a", headers=admin_headers)).json()["items"]
        assert lst[0]["owner_name"] == card["owner_name"], "владелец виден и в списке"

        # Снятие — осознанное действие (человек уволился, показатель передают),
        # и пустое значение должно его снимать, а не значить «не менять».
        r = await client.patch(f"/metrics/{m['id']}", headers=admin_headers, json={"owner_id": None})
        assert r.status_code == 200, r.text
        card = (await client.get(f"/metrics/{m['id']}", headers=admin_headers)).json()["metric"]
        assert card["owner_id"] is None

        # Правка ДРУГОГО поля владельца не трогает: ключа нет — не меняем.
        await client.patch(f"/metrics/{m['id']}", headers=admin_headers, json={"owner_id": viewer["id"]})
        await client.patch(f"/metrics/{m['id']}", headers=admin_headers, json={"description": "текст"})
        card = (await client.get(f"/metrics/{m['id']}", headers=admin_headers)).json()["metric"]
        assert str(card["owner_id"]) == viewer["id"], "описание правили, ответственного — нет"

        # Чужой человек ответственным быть не может: жалобы ушли бы в никуда.
        bad = await client.patch(f"/metrics/{m['id']}", headers=admin_headers,
                                 json={"owner_id": "00000000-0000-0000-0000-000000000000"})
        assert bad.status_code == 400
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from metric_versions where metric_id=$1::uuid", m["id"])
            await conn.execute("delete from metrics where id=$1::uuid", m["id"])


async def test_owner_reaches_tooltip_drill_and_problem_report(client, admin_headers, viewer, ids):
    """Ответственный виден там, где спрашивают «что это за цифра», и получает
    жалобу — при этом общая очередь остаётся."""
    m = await _metric_with_owner(client, admin_headers, "ztest_owner_b", viewer["id"])
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_owner_dash"})).json()["id"]
    try:
        page = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                                  json={"name": "Стр"})).json()
        w = (await client.post(f"/dashboard-pages/{page['id']}/widgets", headers=admin_headers, json={
            "name": "Карточка", "widget_type": "kpi",
            "config": {"metric_code": "ztest_owner_b"}})).json()

        # Подсказка ⓘ называет ответственного.
        wl = (await client.get(f"/dashboard-pages/{page['id']}/widgets", headers=admin_headers)).json()
        tip = next(x["explain"] for x in wl["widgets"] if x["id"] == w["id"])
        assert "Ответственный" in (tip or ""), tip

        # Разбор «из чего складывается» — тоже.
        drill = (await client.get(f"/widgets/{w['id']}/drill", headers=admin_headers)).json()
        assert drill["metrics"][0]["owner_name"], drill["metrics"][0]

        # Жалоба адресуется владельцу: он назван в ответе, в контексте и в теле.
        r = (await client.post(f"/widgets/{w['id']}/report-problem", headers=admin_headers,
                               json={"kind": "wrong_value", "comment": "проверка"})).json()
        assert r["owner_name"], r
        appeal = (await client.get(f"/appeals/{r['appeal_id']}", headers=admin_headers)).json()
        assert appeal["context"]["owner_id"] == viewer["id"]
        assert "Ответственный за показатель" in appeal["messages"][0]["body"]

        # Владелец получил уведомление — но общая очередь не отменена: жалоба
        # по-прежнему видна управляющим (иначе она повиснет, пока он в отпуске).
        async with db.acquire() as conn:
            got = await conn.fetchval(
                "select count(*) from notification_recipients nr "
                "join notification_events e on e.id = nr.notification_event_id "
                "where e.entity_id=$1::uuid and nr.user_id=$2::uuid", r["appeal_id"], viewer["id"])
            staff = await conn.fetchval(
                "select count(*) from notification_recipients nr "
                "join notification_events e on e.id = nr.notification_event_id "
                "where e.entity_id=$1::uuid", r["appeal_id"])
        assert got == 1, "ответственному ушло уведомление"
        assert staff > got, "управляющие тоже уведомлены — очередь остаётся общей"
    finally:
        await purge_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute(
                "delete from appeal_messages where appeal_id in "
                "(select id from appeals where organization_id=$1 and subject like '%ztest_owner%')", ids["org"])
            await conn.execute(
                "delete from appeals where organization_id=$1 and subject like '%ztest_owner%'", ids["org"])
            await conn.execute("delete from metric_versions where metric_id=$1::uuid", m["id"])
            await conn.execute("delete from metrics where id=$1::uuid", m["id"])


async def test_owner_who_is_also_a_manager_is_notified_once(client, admin_headers, moderator_user, ids):
    """Ответственный-модератор не должен получить ДВА уведомления об одном
    обращении: общая рассылка управляющим уже включает его, и второе письмо о
    том же выглядит сбоем системы (поймано живой проверкой 24.08)."""
    m = await _metric_with_owner(client, admin_headers, "ztest_owner_c", moderator_user["id"])
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_owner_dash2"})).json()["id"]
    try:
        page = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                                  json={"name": "Стр"})).json()
        w = (await client.post(f"/dashboard-pages/{page['id']}/widgets", headers=admin_headers, json={
            "name": "Карточка", "widget_type": "kpi",
            "config": {"metric_code": "ztest_owner_c"}})).json()
        r = (await client.post(f"/widgets/{w['id']}/report-problem", headers=admin_headers,
                               json={"kind": "no_data", "comment": "проверка"})).json()
        async with db.acquire() as conn:
            got = await conn.fetchval(
                "select count(*) from notification_recipients nr "
                "join notification_events e on e.id = nr.notification_event_id "
                "where e.entity_id=$1::uuid and nr.user_id=$2::uuid",
                r["appeal_id"], moderator_user["id"])
        assert got == 1, "владелец-управляющий получает ровно одно уведомление"
        assert r["owner_name"], "в ответе он всё равно назван — жалоба адресна"
    finally:
        await purge_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute(
                "delete from appeal_messages where appeal_id in "
                "(select id from appeals where organization_id=$1 and subject like '%ztest_owner%')", ids["org"])
            await conn.execute(
                "delete from appeals where organization_id=$1 and subject like '%ztest_owner%'", ids["org"])
            await conn.execute("delete from metric_versions where metric_id=$1::uuid", m["id"])
            await conn.execute("delete from metrics where id=$1::uuid", m["id"])
