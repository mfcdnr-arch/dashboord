"""Row-level RLS: видимость строк данных по подразделению (миграция 024).

Пока для объекта нет правил — строки видят все. Как только правило появилось —
непривилегированный видит только выданные его отделу строки; привилегированный
и предпросмотр — все. Метрики-формулы не фильтруются (объективны)."""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import db, purge_dashboard

ALL_ROWS = {"Паспорт", "ИНН", "СНИЛС"}


async def test_row_rls_table_and_kpi(client, admin_headers, viewer, seed_dataset):
    async with db.acquire() as conn:
        obj = str(await conn.fetchval("select id from objects where name='t_obj'"))
        org = await conn.fetchval("select organization_id from objects where id=$1::uuid", obj)
        dep = str(await conn.fetchval(
            "insert into departments(organization_id,name) values($1,'ztest_dep_rls') returning id", org))
        await conn.execute("update users set department_id=$1::uuid where id=$2::uuid", dep, viewer["id"])

    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_rowrls"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "P"})).json()["id"]
        wid = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
               json={"name": "T", "widget_type": "table", "config": {"dataset_code": "t_ds"}})).json()["id"]
        kwid = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                json={"name": "K", "widget_type": "kpi", "config": {"dataset_code": "t_ds", "value_field": "plan"}})).json()["id"]
        await client.post(f"/dashboards/{did}/grants", headers=admin_headers,
                          json={"grantee_type": "user", "user_id": viewer["id"]})
        await client.post(f"/dashboards/{did}/publish", headers=admin_headers)

        rows = lambda r: {x["row"] for x in r.json()["rows"]}  # noqa: E731

        # Правил нет → и viewer, и admin видят все строки
        assert rows(await client.get(f"/widgets/{wid}/data", headers=viewer["headers"])) == ALL_ROWS

        # Включаем RLS: отделу viewer разрешён только «Паспорт»
        r = await client.put(f"/objects/{obj}/row-acl/{dep}", headers=admin_headers, json={"row_labels": ["Паспорт"]})
        assert r.status_code == 200, r.text

        # viewer видит только «Паспорт»; admin (привилегированный) — все
        assert rows(await client.get(f"/widgets/{wid}/data", headers=viewer["headers"])) == {"Паспорт"}
        assert rows(await client.get(f"/widgets/{wid}/data", headers=admin_headers)) == ALL_ROWS

        # KPI-сумма по датасету: viewer=только Паспорт (plan=100), admin=180
        assert (await client.get(f"/widgets/{kwid}/data", headers=viewer["headers"])).json()["value"] == 100
        assert (await client.get(f"/widgets/{kwid}/data", headers=admin_headers)).json()["value"] == 180

        # get_row_acl отражает включённость и текущие разрешения
        acl = (await client.get(f"/objects/{obj}/row-acl", headers=admin_headers)).json()
        assert acl["enabled"] is True
        assert set(acl["row_labels"]) == ALL_ROWS  # доступные строки объекта
        dep_rule = next(d for d in acl["departments"] if d["id"] == dep)
        assert dep_rule["row_labels"] == ["Паспорт"]

        # Снятие правил → снова все строки
        await client.put(f"/objects/{obj}/row-acl/{dep}", headers=admin_headers, json={"row_labels": []})
        assert rows(await client.get(f"/widgets/{wid}/data", headers=viewer["headers"])) == ALL_ROWS
    finally:
        await purge_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute("delete from data_row_acl where object_id=$1::uuid", obj)
            await conn.execute("update users set department_id=null where id=$1::uuid", viewer["id"])
            await conn.execute("delete from departments where name='ztest_dep_rls'")


async def test_row_rls_no_department_sees_nothing(client, admin_headers, viewer, seed_dataset):
    """RLS включён у объекта, а у пользователя нет отдела → fail closed (нет строк)."""
    async with db.acquire() as conn:
        obj = str(await conn.fetchval("select id from objects where name='t_obj'"))
        org = await conn.fetchval("select organization_id from objects where id=$1::uuid", obj)
        dep = str(await conn.fetchval(
            "insert into departments(organization_id,name) values($1,'ztest_dep_rls2') returning id", org))
        # viewer БЕЗ отдела (department_id null); правило есть для другого отдела
        await conn.execute("update users set department_id=null where id=$1::uuid", viewer["id"])

    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_rowrls2"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "P"})).json()["id"]
        wid = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
               json={"name": "T", "widget_type": "table", "config": {"dataset_code": "t_ds"}})).json()["id"]
        await client.post(f"/dashboards/{did}/grants", headers=admin_headers,
                          json={"grantee_type": "user", "user_id": viewer["id"]})
        await client.post(f"/dashboards/{did}/publish", headers=admin_headers)
        await client.put(f"/objects/{obj}/row-acl/{dep}", headers=admin_headers, json={"row_labels": ["Паспорт"]})

        r = await client.get(f"/widgets/{wid}/data", headers=viewer["headers"])
        assert r.json()["rows"] == []  # нет отдела → ни одной строки
    finally:
        await purge_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute("delete from data_row_acl where object_id=$1::uuid", obj)
            await conn.execute("delete from departments where name='ztest_dep_rls2'")
