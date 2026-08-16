"""Доступ к дашбордам глазами СОТРУДНИКА (пп. 10–11 списка заказчика).

До сих пор доступ выдавался только «от дашборда»: чтобы открыть человеку пять
отчётов, нужно было пять раз пройти один и тот же путь, а чтобы понять, что
ему видно, — обойти все дашборды по очереди.

Три вещи, которые здесь проверяются и стоят дороже самой функции:

1. **Второй системы прав нет.** Экран читает и пишет те же `access_grants`, а
   итоговую видимость считает та же функция RLS, что и обычный список
   дашбордов. Признак `visible` обязан совпадать с тем, что человек реально
   видит, иначе администратор поверит галочке, а зритель увидит пустой список.

2. **Грант на РОЛЬ отсюда не снимается.** Он выдан не этому человеку, а всем
   носителям роли: «убрать у Иванова» тихо отобрало бы доступ у всего отдела.

3. **Пакетная операция идемпотентна.** Панель отправляет разницу целиком, и
   падение на одной строке из десяти оставило бы доступы наполовину выданными.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db


async def _mk(client, headers, name):
    r = await client.post("/dashboards", headers=headers, json={"name": name})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _drop(dids):
    async with db.acquire() as conn:
        for did in dids:
            await conn.execute("delete from access_grants where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from audit_log where entity_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_grant_and_revoke_in_bulk(client, admin_headers, viewer):
    """Пакетная выдача двух дашбордов и снятие одного — тем же механизмом грантов."""
    a = await _mk(client, admin_headers, "ztest_ua_a")
    b = await _mk(client, admin_headers, "ztest_ua_b")
    try:
        for did in (a, b):
            await client.post(f"/dashboards/{did}/publish", headers=admin_headers, json={})

        r = await client.post(f"/users/{viewer['id']}/dashboard-access", headers=admin_headers,
                              json={"grant": [a, b], "revoke": []})
        assert r.status_code == 200, r.text
        assert r.json()["granted"] == 2

        # Проверяем не «галочку», а то, что зритель реально видит оба отчёта.
        seen = {i["id"] for i in (await client.get("/dashboards?limit=200",
                                                   headers=viewer["headers"])).json()["items"]}
        assert {a, b} <= seen

        # Повтор той же выдачи — не ошибка и не дубль гранта.
        r = await client.post(f"/users/{viewer['id']}/dashboard-access", headers=admin_headers,
                              json={"grant": [a, b], "revoke": []})
        assert r.status_code == 200 and r.json()["granted"] == 0
        async with db.acquire() as conn:
            cnt = await conn.fetchval(
                "select count(*) from access_grants where dashboard_id=$1::uuid and user_id=$2::uuid",
                a, viewer["id"])
        assert cnt == 1, "повторная выдача не должна плодить гранты"

        # Снятие одного: второй остаётся. Снятие несуществующего — тоже не ошибка.
        r = await client.post(f"/users/{viewer['id']}/dashboard-access", headers=admin_headers,
                              json={"grant": [], "revoke": [a, a]})
        assert r.status_code == 200 and r.json()["revoked"] == 1
        seen = {i["id"] for i in (await client.get("/dashboards?limit=200",
                                                   headers=viewer["headers"])).json()["items"]}
        assert a not in seen and b in seen
    finally:
        await _drop([a, b])


async def test_visible_matches_real_rls(client, admin_headers, viewer):
    """`visible` считает та же RLS: выданный, но НЕопубликованный не виден."""
    did = await _mk(client, admin_headers, "ztest_ua_draft")
    try:
        await client.post(f"/users/{viewer['id']}/dashboard-access", headers=admin_headers,
                          json={"grant": [did], "revoke": []})
        row = _row(await client.get(f"/users/{viewer['id']}/dashboard-access",
                                    headers=admin_headers), did)
        assert row["granted"] is True
        assert row["publication_status"] == "draft"
        assert row["visible"] is False, "черновик зритель не увидит даже с грантом"
        seen = {i["id"] for i in (await client.get("/dashboards?limit=200",
                                                   headers=viewer["headers"])).json()["items"]}
        assert did not in seen, "экран доступа не должен обещать больше, чем показывает список"

        await client.post(f"/dashboards/{did}/publish", headers=admin_headers, json={})
        row = _row(await client.get(f"/users/{viewer['id']}/dashboard-access",
                                    headers=admin_headers), did)
        assert row["visible"] is True
    finally:
        await _drop([did])


async def test_role_grant_is_shown_but_not_revocable(client, admin_headers, viewer, ids):
    """Доступ через роль виден как «через роль», но личным снятием не убирается."""
    did = await _mk(client, admin_headers, "ztest_ua_role")
    try:
        await client.post(f"/dashboards/{did}/publish", headers=admin_headers, json={})
        async with db.acquire() as conn:
            role_id = await conn.fetchval(
                "select id from roles where code='user' and organization_id=$1", ids["org"])
        r = await client.post(f"/dashboards/{did}/grants", headers=admin_headers,
                              json={"grantee_type": "role", "role_id": str(role_id)})
        assert r.status_code in (200, 201), r.text

        row = _row(await client.get(f"/users/{viewer['id']}/dashboard-access",
                                    headers=admin_headers), did)
        assert row["granted"] is False, "личного гранта нет — доступ идёт от роли"
        assert row["via_roles"], "источник доступа должен быть назван"
        assert row["visible"] is True

        # Попытка «снять у этого человека» не должна трогать грант роли.
        r = await client.post(f"/users/{viewer['id']}/dashboard-access", headers=admin_headers,
                              json={"grant": [], "revoke": [did]})
        assert r.status_code == 200 and r.json()["revoked"] == 0
        seen = {i["id"] for i in (await client.get("/dashboards?limit=200",
                                                   headers=viewer["headers"])).json()["items"]}
        assert did in seen, "грант роли снимается на дашборде, а не в карточке одного сотрудника"
    finally:
        await _drop([did])


async def test_access_screen_is_admin_only(client, viewer, moderator_user, ids):
    """Зритель и модератор не управляют доступами сотрудников: это работа администратора."""
    for headers in (viewer["headers"], moderator_user["headers"]):
        r = await client.get(f"/users/{viewer['id']}/dashboard-access", headers=headers)
        assert r.status_code == 403, r.text
        r = await client.post(f"/users/{viewer['id']}/dashboard-access", headers=headers,
                              json={"grant": [], "revoke": []})
        assert r.status_code == 403


async def test_unknown_user_is_404(client, admin_headers):
    r = await client.get("/users/00000000-0000-0000-0000-000000000000/dashboard-access",
                         headers=admin_headers)
    assert r.status_code == 404


def _row(resp, did):
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    return next(i for i in items if i["dashboard_id"] == did)
