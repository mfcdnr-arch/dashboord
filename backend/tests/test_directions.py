"""Направления дашбордов (этап 3, 29.09.2026).

Решения заказчика 23.09: группа внутри «Дашбордов»; у дашборда одно
направление; доступ прежний — направление только группирует; система
предлагает разложить, администратор подтверждает.

Главное здесь — не «работает», а «не проговаривается»: название направления
и число дашбордов в нём не должны сообщать зрителю о дашбордах, которых ему
не видно.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import db, purge_dashboard  # noqa: E402

DENIED = {403, 404}


async def _dash(client, headers, name, **extra):
    r = await client.post("/dashboards", headers=headers, json={"name": name, "force": True, **extra})
    assert r.status_code in (200, 201), r.text
    return r.json()


async def _publish_and_grant(did, viewer_id, admin_id):
    async with db.acquire() as conn:
        await conn.execute("update dashboards set publication_status='published' where id=$1::uuid", did)
        await conn.execute(
            "insert into access_grants(scope, dashboard_id, grantee_type, user_id, granted_by) "
            "values('dashboard', $1::uuid, 'user', $2::uuid, $3)", did, viewer_id, admin_id)


async def _cleanup(dids):
    for did in dids:
        await purge_dashboard(did)
    async with db.acquire() as conn:
        await conn.execute("delete from dashboard_directions where name like 'ztest_%'")


async def test_crud_and_names_are_unique_without_case(client, admin_headers):
    """Имя уникально без учёта регистра и пробелов; удаление оставляет дашборд."""
    dids = []
    try:
        r = await client.post("/dashboard-directions", headers=admin_headers, json={"name": "  ztest_РЦО  "})
        assert r.status_code == 201, r.text
        did_dir = r.json()["id"]
        assert r.json()["name"] == "ztest_РЦО", "внешние пробелы убираются"
        dup = await client.post("/dashboard-directions", headers=admin_headers, json={"name": "ZTEST_рцо"})
        assert dup.status_code == 400 and "уже есть" in dup.json()["detail"]

        ren = await client.patch(f"/dashboard-directions/{did_dir}", headers=admin_headers,
                                 json={"name": "ztest_РЦО и окна"})
        assert ren.status_code == 200 and ren.json()["name"] == "ztest_РЦО и окна"

        d = await _dash(client, admin_headers, "ztest_dir_dash", direction_id=did_dir)
        dids.append(str(d["id"]))
        assert str(d["direction_id"]) == did_dir

        rm = await client.delete(f"/dashboard-directions/{did_dir}", headers=admin_headers)
        assert rm.status_code == 200 and rm.json()["dashboards_freed"] == 1
        async with db.acquire() as conn:
            left = await conn.fetchrow("select direction_id from dashboards where id=$1::uuid", dids[0])
        assert left is not None and left["direction_id"] is None, "дашборд остаётся, без направления"
    finally:
        await _cleanup(dids)


async def test_viewer_sees_only_directions_of_visible_dashboards(client, admin_headers, viewer, ids):
    """🔴 Счётчик и само направление — только по видимым зрителю дашбордам.

    Иначе «ztest_Закрытое · отчётов: 1» сообщило бы зрителю о дашборде, к
    которому у него нет доступа.
    """
    dids = []
    try:
        open_dir = (await client.post("/dashboard-directions", headers=admin_headers,
                                      json={"name": "ztest_Открытое"})).json()["id"]
        closed_dir = (await client.post("/dashboard-directions", headers=admin_headers,
                                        json={"name": "ztest_Закрытое"})).json()["id"]
        seen = await _dash(client, admin_headers, "ztest_dir_seen", direction_id=open_dir)
        hidden = await _dash(client, admin_headers, "ztest_dir_hidden", direction_id=open_dir)
        secret = await _dash(client, admin_headers, "ztest_dir_secret", direction_id=closed_dir)
        dids += [str(seen["id"]), str(hidden["id"]), str(secret["id"])]
        await _publish_and_grant(str(seen["id"]), viewer["id"], str(ids["admin"]))

        mine = (await client.get("/dashboard-directions", headers=viewer["headers"])).json()
        names = {i["name"]: i["dashboards"] for i in mine["items"]}
        assert "ztest_Закрытое" not in names, "направление без видимых дашбордов зрителю не показывается"
        assert names.get("ztest_Открытое") == 1, "в счёт идёт только видимый зрителю дашборд"
        assert mine["manage"] is False

        # Контрольная группа: управляющий видит всё, включая пустые для зрителя.
        staff = (await client.get("/dashboard-directions", headers=admin_headers)).json()
        snames = {i["name"]: i["dashboards"] for i in staff["items"]}
        assert snames["ztest_Закрытое"] == 1 and snames["ztest_Открытое"] == 2

        # Фильтр списка по направлению не расширяет видимость.
        lst = (await client.get(f"/dashboards?direction_id={open_dir}", headers=viewer["headers"])).json()
        assert [i["name"] for i in lst["items"]] == ["ztest_dir_seen"]
        assert lst["items"][0]["direction_name"] == "ztest_Открытое"
    finally:
        await _cleanup(dids)


async def test_viewer_cannot_manage_directions(client, admin_headers, viewer):
    """Правка — управляющим; контрольная группа: зритель читает список (200)."""
    vh = viewer["headers"]
    assert (await client.get("/dashboard-directions", headers=vh)).status_code == 200
    assert (await client.post("/dashboard-directions", headers=vh, json={"name": "ztest_x"})).status_code in DENIED
    assert (await client.post("/dashboard-directions/assign", headers=vh,
                              json={"dashboard_ids": ["00000000-0000-0000-0000-000000000000"]})).status_code in DENIED
    assert (await client.get("/dashboard-directions/proposal", headers=vh)).status_code in DENIED


async def test_proposal_is_confirmed_by_admin_not_moderator(client, admin_headers, moderator_user):
    """Решение 23.09: раскладку всего списка подтверждает администратор."""
    mh = moderator_user["headers"]
    assert (await client.get("/dashboard-directions/proposal", headers=mh)).status_code == 403
    assert (await client.post("/dashboard-directions/proposal/apply", headers=mh,
                              json={"groups": []})).status_code == 403
    # Модератор при этом ведёт направления и назначает их дашбордам.
    r = await client.post("/dashboard-directions", headers=mh, json={"name": "ztest_от_модератора"})
    try:
        assert r.status_code == 201
    finally:
        await _cleanup([])


async def test_bulk_assign_is_all_or_nothing(client, admin_headers):
    """🔴 Массовое назначение — одной операцией: неизвестный дашборд — и не тронут ни один.

    Массовое перемещение в папку идёт циклом запросов с экрана, и сбой на
    середине оставляет часть переложенной без сообщения, какую.
    """
    dids = []
    try:
        a = await _dash(client, admin_headers, "ztest_dir_bulk_a")
        b = await _dash(client, admin_headers, "ztest_dir_bulk_b")
        dids += [str(a["id"]), str(b["id"])]
        bad = await client.post("/dashboard-directions/assign", headers=admin_headers, json={
            "dashboard_ids": dids + ["00000000-0000-0000-0000-000000000000"], "new_name": "ztest_Пакет"})
        assert bad.status_code == 404
        async with db.acquire() as conn:
            assert await conn.fetchval(
                "select count(*) from dashboards where id = any($1::uuid[]) and direction_id is not null",
                dids) == 0
            assert await conn.fetchval(
                "select count(*) from dashboard_directions where name='ztest_Пакет'") == 0, \
                "новое направление не должно остаться от неудачной операции"

        ok = await client.post("/dashboard-directions/assign", headers=admin_headers,
                               json={"dashboard_ids": dids, "new_name": "ztest_Пакет"})
        assert ok.status_code == 200 and ok.json()["dashboards"] == 2
        # Имя, совпавшее с существующим, ведёт в него, а не плодит второе.
        again = await client.post("/dashboard-directions/assign", headers=admin_headers,
                                  json={"dashboard_ids": dids[:1], "new_name": "ZTEST_пакет"})
        assert again.json()["direction_id"] == ok.json()["direction_id"]

        lst = (await client.get("/dashboards?direction_id=none&q=ztest_dir_bulk", headers=admin_headers)).json()
        assert lst["total"] == 0
        off = await client.post("/dashboard-directions/assign", headers=admin_headers,
                                json={"dashboard_ids": dids[:1]})
        assert off.json()["direction_id"] is None
        lst = (await client.get("/dashboards?direction_id=none&q=ztest_dir_bulk", headers=admin_headers)).json()
        assert [i["name"] for i in lst["items"]] == ["ztest_dir_bulk_a"]
    finally:
        await _cleanup(dids)


async def test_proposal_groups_by_object_family_and_reuses_existing(client, admin_headers):
    """Предложение: по началу имени объекта, совпавшее имя — в существующее направление."""
    from app.modules.dashboards._directions import family_of

    assert family_of("Статистика услуг — МВД", "x") == "Статистика услуг"
    assert family_of("РЦО — окна и часы", "x") == "РЦО"
    assert family_of("МФЦ ДНР", "x") == "МФЦ ДНР"
    assert family_of(None, "РЦО: ежедневный отчёт") == "РЦО"

    dids = []
    try:
        existing = (await client.post("/dashboard-directions", headers=admin_headers,
                                      json={"name": "ztest_Семья"})).json()["id"]
        for n in ("ztest_Семья: первый", "ztest_Семья: второй", "ztest_Одиночка — отчёт"):
            dids.append(str((await _dash(client, admin_headers, n))["id"]))
        prop = (await client.get("/dashboard-directions/proposal", headers=admin_headers)).json()
        groups = {g["name"]: g for g in prop["groups"]}
        fam = groups["ztest_Семья"]
        assert fam["direction_id"] == existing and "уже есть" in fam["why"]
        assert {d["name"] for d in fam["dashboards"]} == {"ztest_Семья: первый", "ztest_Семья: второй"}
        assert "ztest_Одиночка" in groups

        applied = await client.post("/dashboard-directions/proposal/apply", headers=admin_headers, json={
            "groups": [{"name": "ztest_Семья", "dashboard_ids": [d["id"] for d in fam["dashboards"]]},
                       {"name": "ztest_Одиночка", "dashboard_ids": [groups["ztest_Одиночка"]["dashboards"][0]["id"]]}]})
        assert applied.status_code == 200, applied.text
        assert applied.json() == {"directions_created": 1, "dashboards_assigned": 3}
        again = (await client.get("/dashboard-directions/proposal", headers=admin_headers)).json()
        assert not any(g["name"].startswith("ztest_") for g in again["groups"]), "разложенное не предлагается снова"
    finally:
        await _cleanup(dids)


async def test_wizard_builds_into_a_new_direction(client, admin_headers, seed_dataset, ids):
    """Мастер «✨ Собрать»: новый дашборд сразу в направлении; имя — существующее или новое."""
    from test_auto_build import _cleanup_fields, _seed_fields

    rel = await _seed_fields(ids["org"])
    obj = str(rel["object_id"])
    did = None
    try:
        r = await client.post("/dashboards/auto", headers=admin_headers, json={
            "object_id": obj, "name": "ztest_dir_auto", "force": True, "new_direction": "ztest_Мастер"})
        assert r.status_code in (200, 201), r.text
        did = r.json()["dashboard_id"]
        got = (await client.get(f"/dashboards/{did}", headers=admin_headers)).json()
        assert got["dashboard"]["direction_name"] == "ztest_Мастер"
        sug = (await client.get(f"/dashboard-directions/for-object/{obj}", headers=admin_headers)).json()
        assert sug["suggestion"]["name"] == "ztest_Мастер", "следующий дашборд объекта — туда же"
    finally:
        await _cleanup([did] if did else [])
        await _cleanup_fields(rel)


async def test_direction_changes_are_audited(client, admin_headers, ids):
    """Создание, переименование и удаление направления — в журнале действий."""
    r = await client.post("/dashboard-directions", headers=admin_headers, json={"name": "ztest_Аудит"})
    did = r.json()["id"]
    await client.patch(f"/dashboard-directions/{did}", headers=admin_headers, json={"name": "ztest_Аудит 2"})
    await client.delete(f"/dashboard-directions/{did}", headers=admin_headers)
    async with db.acquire() as conn:
        acts = [r["action"] for r in await conn.fetch(
            "select action::text from audit_log where entity_type='direction' and entity_id=$1::uuid "
            "order by created_at", did)]
        await conn.execute("delete from audit_log where entity_type='direction' and entity_id=$1::uuid", did)
    assert acts == ["create", "update", "delete"]


async def test_name_race_is_a_clear_refusal(ids, monkeypatch):
    """🔴 Два одновременных создания одного имени: второе — понятный отказ, не 500.

    Проверка имени и вставка — два шага, и оба запроса проходят проверку раньше,
    чем кто-то вставит. Окно воспроизводится детерминированно: проверка «не
    видит» соперника, решает уникальный индекс.
    """
    from app.modules.dashboards import _directions as dirs
    from app.modules.dashboards._base import DashboardError

    try:
        async with db.acquire() as conn:
            first = await dirs.create_direction(conn, ids["org"], ids["admin"], "ztest_Гонка")

            async def blind(*_a, **_k):
                return None
            monkeypatch.setattr(dirs, "_by_name", blind)
            with pytest.raises(DashboardError, match="уже есть"):
                await dirs.create_direction(conn, ids["org"], ids["admin"], "ZTEST_гонка")
            other = await dirs.create_direction(conn, ids["org"], ids["admin"], "ztest_Другое")
            with pytest.raises(DashboardError, match="уже есть"):
                await dirs.update_direction(conn, ids["org"], other["id"], {"name": "ztest_гонка"})
            assert first["name"] == "ztest_Гонка"
    finally:
        await _cleanup([])
