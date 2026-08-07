"""Управление объектами и папками: переименование (имя/код/описание) и удаление.

Ключевое требование — удалять можно ТОЛЬКО пустое. На объект завязаны каскады
(canonical_fields, data_row_acl) и обнуление ссылок (folders.object_id,
dataset_releases.object_id), поэтому «тихое» удаление уничтожило бы справочник
полей и оторвало выпуски от объекта. Тесты фиксируют и отказ с разбивкой того,
что мешает, и то, что после очистки удаление проходит.
"""
import pytest

from app import db

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _purge_objects(*object_ids: str):
    """Прямая уборка объектов с папками — вместе с их записями контура доступа.

    Тесты создают папки в обход эндпоинта удаления, а securable_objects связан
    с folders логическим FK: без явной чистки в dev-БД копятся висячие строки.
    """
    async with db.acquire() as conn:
        await conn.execute(
            "delete from securable_objects where object_type='folder' and object_id in "
            "(select id from folders where object_id = any($1::uuid[]))", list(object_ids))
        await conn.execute("delete from folders where object_id = any($1::uuid[])", list(object_ids))
        await conn.execute("delete from canonical_fields where object_id = any($1::uuid[])", list(object_ids))
        await conn.execute("delete from objects where id = any($1::uuid[])", list(object_ids))


async def _audit(entity_type: str, entity_id: str):
    async with db.acquire() as conn:
        return await conn.fetch(
            "select action, old_data, new_data from audit_log "
            "where entity_type=$1 and entity_id=$2::uuid order by created_at",
            entity_type, entity_id,
        )


async def test_update_object_fields(client, admin_headers):
    obj = (await client.post("/objects", headers=admin_headers, json={"name": "ztest_om_obj"})).json()
    other = (await client.post("/objects", headers=admin_headers, json={"name": "ztest_om_other"})).json()
    try:
        r = await client.patch(f"/objects/{obj['id']}", headers=admin_headers,
                               json={"name": "ztest_om_renamed", "code": "OM-01", "description": "описание"})
        assert r.status_code == 200
        assert r.json()["name"] == "ztest_om_renamed"
        assert r.json()["code"] == "OM-01"
        assert r.json()["description"] == "описание"

        # список отдаёт код — форма правки на фронте заполняется из него
        item = next(o for o in (await client.get("/objects", headers=admin_headers)).json() if o["id"] == obj["id"])
        assert item["code"] == "OM-01"

        # частичное обновление не затирает соседние поля
        r = await client.patch(f"/objects/{obj['id']}", headers=admin_headers, json={"description": None})
        assert r.status_code == 200 and r.json()["description"] is None and r.json()["code"] == "OM-01"

        # имя занято другим объектом
        r = await client.patch(f"/objects/{obj['id']}", headers=admin_headers, json={"name": "ztest_om_other"})
        assert r.status_code == 409

        # пустое тело и пустое имя
        assert (await client.patch(f"/objects/{obj['id']}", headers=admin_headers, json={})).status_code == 400
        assert (await client.patch(f"/objects/{obj['id']}", headers=admin_headers, json={"name": "   "})).status_code == 400

        # несуществующий объект
        r = await client.patch("/objects/00000000-0000-0000-0000-000000000000",
                               headers=admin_headers, json={"name": "x"})
        assert r.status_code == 404

        rows = await _audit("object", obj["id"])
        assert [x["action"] for x in rows] == ["update", "update"]
    finally:
        await _purge_objects(obj["id"], other["id"])


async def test_delete_object_only_when_empty(client, admin_headers):
    obj = (await client.post("/objects", headers=admin_headers, json={"name": "ztest_om_del"})).json()
    folder = (await client.post(f"/objects/{obj['id']}/folders",
                                headers=admin_headers, json={"name": "ztest_om_f"})).json()
    ok = False
    try:
        r = await client.delete(f"/objects/{obj['id']}", headers=admin_headers)
        assert r.status_code == 409
        assert "папок: 1" in r.json()["detail"]

        # канонические поля объекта тоже держат удаление (их каскад — самый опасный)
        async with db.acquire() as conn:
            await conn.execute(
                "insert into canonical_fields(object_id, code, name) values($1::uuid,'zt_f','Поле')", obj["id"])
        await client.delete(f"/objects/{obj['id']}/folders/{folder['id']}", headers=admin_headers)
        r = await client.delete(f"/objects/{obj['id']}", headers=admin_headers)
        assert r.status_code == 409 and "канонических полей: 1" in r.json()["detail"]

        async with db.acquire() as conn:
            await conn.execute("delete from canonical_fields where object_id=$1::uuid", obj["id"])

        assert (await client.delete(f"/objects/{obj['id']}", headers=admin_headers)).status_code == 204
        assert (await client.delete(f"/objects/{obj['id']}", headers=admin_headers)).status_code == 404
        assert obj["id"] not in {o["id"] for o in (await client.get("/objects", headers=admin_headers)).json()}
        ok = True

        rows = await _audit("object", obj["id"])
        assert rows[-1]["action"] == "delete"
    finally:
        if not ok:
            await _purge_objects(obj["id"])


async def test_folder_rename_delete_and_isolation(client, admin_headers):
    obj = (await client.post("/objects", headers=admin_headers, json={"name": "ztest_om_fobj"})).json()
    other = (await client.post("/objects", headers=admin_headers, json={"name": "ztest_om_fother"})).json()
    folder = (await client.post(f"/objects/{obj['id']}/folders",
                                headers=admin_headers, json={"name": "ztest_om_parent"})).json()
    sub = (await client.post(f"/objects/{obj['id']}/folders", headers=admin_headers,
                             json={"name": "ztest_om_sub", "parent_folder_id": folder["id"]})).json()
    try:
        r = await client.patch(f"/objects/{obj['id']}/folders/{folder['id']}",
                               headers=admin_headers, json={"name": "ztest_om_parent2"})
        assert r.status_code == 200 and r.json()["name"] == "ztest_om_parent2"

        # папку чужого объекта не видно — ни на правку, ни на удаление
        assert (await client.patch(f"/objects/{other['id']}/folders/{folder['id']}",
                                   headers=admin_headers, json={"name": "x"})).status_code == 404
        assert (await client.delete(f"/objects/{other['id']}/folders/{folder['id']}",
                                    headers=admin_headers)).status_code == 404

        # вложенная папка держит удаление родительской
        r = await client.delete(f"/objects/{obj['id']}/folders/{folder['id']}", headers=admin_headers)
        assert r.status_code == 409 and "вложенных папок: 1" in r.json()["detail"]

        # дашборд в папке — тоже стоп-фактор
        did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_om_dash"})).json()["id"]
        await client.post(f"/dashboards/{did}/folder", headers=admin_headers, json={"folder_id": sub["id"]})
        r = await client.delete(f"/objects/{obj['id']}/folders/{sub['id']}", headers=admin_headers)
        assert r.status_code == 409 and "дашбордов: 1" in r.json()["detail"]
        await client.post(f"/dashboards/{did}/folder", headers=admin_headers, json={"folder_id": None})

        assert (await client.delete(f"/objects/{obj['id']}/folders/{sub['id']}", headers=admin_headers)).status_code == 204
        assert (await client.delete(f"/objects/{obj['id']}/folders/{folder['id']}", headers=admin_headers)).status_code == 204

        # запись контура доступа удалённой папки не осталась висеть
        async with db.acquire() as conn:
            left = await conn.fetchval(
                "select count(*) from securable_objects where object_type='folder' and object_id = any($1::uuid[])",
                [folder["id"], sub["id"]])
        assert left == 0

        from conftest import purge_dashboard
        await purge_dashboard(did)
    finally:
        await _purge_objects(obj["id"], other["id"])


async def test_manage_role_required(client, admin_headers, viewer):
    obj = (await client.post("/objects", headers=admin_headers, json={"name": "ztest_om_perm"})).json()
    folder = (await client.post(f"/objects/{obj['id']}/folders",
                                headers=admin_headers, json={"name": "ztest_om_permf"})).json()
    try:
        assert (await client.patch(f"/objects/{obj['id']}", headers=viewer["headers"],
                                   json={"name": "hack"})).status_code == 403
        assert (await client.delete(f"/objects/{obj['id']}", headers=viewer["headers"])).status_code == 403
        assert (await client.patch(f"/objects/{obj['id']}/folders/{folder['id']}", headers=viewer["headers"],
                                   json={"name": "hack"})).status_code == 403
        assert (await client.delete(f"/objects/{obj['id']}/folders/{folder['id']}",
                                    headers=viewer["headers"])).status_code == 403
        # ничего не изменилось
        assert (await client.get("/objects", headers=admin_headers)).json()
        item = next(o for o in (await client.get("/objects", headers=admin_headers)).json() if o["id"] == obj["id"])
        assert item["name"] == "ztest_om_perm"
    finally:
        await _purge_objects(obj["id"])
