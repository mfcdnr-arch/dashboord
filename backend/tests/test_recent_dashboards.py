"""«Недавно смотрел» (п. 10 списка предложений): последние открытые ЭТИМ
человеком отчёты. Своего счётчика нет — берём просмотры из журнала (audit_log,
action=view), поэтому полоса не может разойтись с отчётом популярности."""
import pytest

from app import db

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _purge(*dids):
    async with db.acquire() as conn:
        for did in dids:
            await conn.execute("delete from audit_log where entity_id=$1::uuid", did)
            await conn.execute("delete from access_grants where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_recent_lists_last_opened_first_and_without_duplicates(client, admin_headers):
    a = (await client.post("/dashboards", headers=admin_headers,
                           json={"name": "ztest_recent_a"})).json()["id"]
    b = (await client.post("/dashboards", headers=admin_headers,
                           json={"name": "ztest_recent_b"})).json()["id"]
    try:
        # Пока не открывали — в «недавних» их нет: полоса показывает то, что
        # человек смотрел, а не то, что существует в системе.
        items = (await client.get("/dashboards/recent", headers=admin_headers)).json()["items"]
        assert not any(i["id"] in (a, b) for i in items)

        await client.get(f"/dashboards/{a}", headers=admin_headers)
        await client.get(f"/dashboards/{b}", headers=admin_headers)

        items = (await client.get("/dashboards/recent", headers=admin_headers)).json()["items"]
        ours = [i for i in items if i["id"] in (a, b)]
        assert [i["id"] for i in ours] == [b, a], "свежие сверху"
        assert ours[0]["name"] == "ztest_recent_b" and ours[0]["viewed_at"]

        # Повторное открытие в пределах окна троттлинга не должно раздваивать
        # строку: отчёт в полосе один, сколько бы раз его ни открывали.
        await client.get(f"/dashboards/{b}", headers=admin_headers)
        items = (await client.get("/dashboards/recent", headers=admin_headers)).json()["items"]
        assert [i["id"] for i in items].count(b) == 1

        # limit — сколько плиток показываем.
        one = (await client.get("/dashboards/recent?limit=1", headers=admin_headers)).json()["items"]
        assert len(one) == 1 and one[0]["id"] == b
    finally:
        await _purge(a, b)


async def test_recent_is_personal_and_follows_access(client, admin_headers, viewer):
    """Полоса личная, а видимость — та же, что у общего списка: отозвали
    доступ — отчёт из «недавних» исчез (иначе полоса называла бы отчёты,
    которых человеку видеть уже нельзя)."""
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_recent_acl"})).json()["id"]
    try:
        await client.post(f"/dashboards/{did}/publish", headers=admin_headers, json={})
        await client.get(f"/dashboards/{did}", headers=admin_headers)

        # Администратор его открыл — у зрителя в «недавних» пусто: полоса про
        # СВОИ просмотры, а не про чужие.
        seen = (await client.get("/dashboards/recent", headers=viewer["headers"])).json()["items"]
        assert not any(i["id"] == did for i in seen)

        await client.post(f"/dashboards/{did}/grants", headers=admin_headers,
                          json={"grantee_type": "user", "user_id": viewer["id"]})
        assert (await client.get(f"/dashboards/{did}", headers=viewer["headers"])).status_code == 200
        seen = (await client.get("/dashboards/recent", headers=viewer["headers"])).json()["items"]
        assert any(i["id"] == did for i in seen), "свой просмотр в полосе есть"

        async with db.acquire() as conn:
            await conn.execute("delete from access_grants where dashboard_id=$1::uuid", did)
        seen = (await client.get("/dashboards/recent", headers=viewer["headers"])).json()["items"]
        assert not any(i["id"] == did for i in seen), "доступ отозван — из полосы ушёл"
    finally:
        await _purge(did)


async def test_recent_drops_archived_and_deleted(client, admin_headers):
    """Архивный отчёт в полосе не показываем (для него отдельный раздел), а
    удалённый исчезает сам: просмотры в журнале остаются — он отвечает на
    вопрос «что было», — но открывать уже нечего."""
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_recent_arch"})).json()["id"]
    try:
        await client.get(f"/dashboards/{did}", headers=admin_headers)
        items = (await client.get("/dashboards/recent", headers=admin_headers)).json()["items"]
        assert any(i["id"] == did for i in items)

        async with db.acquire() as conn:
            await conn.execute("update dashboards set publication_status='archived' where id=$1::uuid", did)
        items = (await client.get("/dashboards/recent", headers=admin_headers)).json()["items"]
        assert not any(i["id"] == did for i in items)

        async with db.acquire() as conn:
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)
        r = await client.get("/dashboards/recent", headers=admin_headers)
        assert r.status_code == 200 and not any(i["id"] == did for i in r.json()["items"])
    finally:
        await _purge(did)
