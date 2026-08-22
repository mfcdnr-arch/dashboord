"""Блок «На что посмотреть»: замечания к данным прямо на дашборде.

Проверки качества выпуска (ingestion/quality) видел только модератор и только в
момент нажатия «Выпустить». Здесь те же правила применяются к уже выпущенным
данным, поэтому дашборд и очередь выпуска не могут говорить об одних данных
разное.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import db, purge_dashboard  # noqa: E402

CODE = "ztest_att_ds"


async def _seed(ids, second_values):
    """Две недели одной формы: вторая повторяет первую в строке «Горловка»."""
    async with db.acquire() as conn:
        obj = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_att_obj') returning id", ids["org"])
        for code, name in (("itogo", "Заявлений принято нарастающим итогом"),
                           ("nedelya", "Заявлений принято за отчетную неделю")):
            await conn.execute(
                "insert into canonical_fields(object_id,code,name,data_type) values($1,$2,$3,'number')",
                obj, code, name)
        for per, vals in (("2026-04-01", {"Горловка": (100, 10), "Донецк": (200, 20)}), ("2026-04-08", second_values)):
            rel = await conn.fetchval(
                "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,created_by,object_id) "
                "values($1,$2,'Форма МФЦ','released',$3::text::date,$4,$5) returning id",
                ids["org"], CODE, per, ids["admin"], obj)
            for i, (row, (tot, week)) in enumerate(vals.items()):
                await conn.execute(
                    "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
                    "values($1,$2,$3,'itogo',$4)", rel, i, row, tot)
                await conn.execute(
                    "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
                    "values($1,$2,$3,'nedelya',$4)", rel, i, row, week)
        return str(obj)


async def _cleanup(ids, obj):
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_releases where code=$1", CODE)
        await conn.execute("delete from canonical_fields where object_id=$1::uuid", obj)
        await conn.execute("delete from objects where name='ztest_att_obj' and organization_id=$1", ids["org"])


async def test_attention_repeats_what_moderator_would_see(client, admin_headers, ids):
    """Строка, скопированная с прошлой недели, и уменьшившийся итог — оба
    замечания доходят до дашборда."""
    obj = await _seed(ids, {"Горловка": (100, 10), "Донецк": (150, 20)})
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_att"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "P"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "K", "widget_type": "kpi",
                                "config": {"dataset_code": CODE, "value_field": "itogo"}})
        res = (await client.get(f"/dashboard-pages/{pid}/attention", headers=admin_headers)).json()
        assert res["datasets_checked"] == 1
        item = res["items"][0]
        assert item["dataset_code"] == CODE and item["period"] == "2026-04-08"
        codes = {w["code"] for w in item["warnings"]}
        # «Горловка» повторяет прошлую неделю дословно, «Донецк» просел с 200 до 150.
        assert "same_as_previous" in codes and "cumulative_drop" in codes
        same = next(w for w in item["warnings"] if w["code"] == "same_as_previous")
        assert "Горловка" in same["message"] and "Донецк" not in same["message"]
    finally:
        await purge_dashboard(did)
        await _cleanup(ids, obj)


async def test_attention_is_silent_when_data_is_fine(client, admin_headers, ids):
    """Данные обновились и растут — блок молчит: пустой список, а не «всё ок»."""
    obj = await _seed(ids, {"Горловка": (140, 40), "Донецк": (260, 60)})
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_att_ok"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "P"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "K", "widget_type": "kpi",
                                "config": {"dataset_code": CODE, "value_field": "itogo"}})
        res = (await client.get(f"/dashboard-pages/{pid}/attention", headers=admin_headers)).json()
        assert res["items"] == []

        # Страница без датасетных виджетов — проверять нечего, и это не ошибка.
        pid2 = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "T"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid2}/widgets", headers=admin_headers,
                          json={"name": "txt", "widget_type": "text", "config": {"heading": "Привет"}})
        res2 = (await client.get(f"/dashboard-pages/{pid2}/attention", headers=admin_headers)).json()
        assert res2 == {"items": [], "datasets_checked": 0}
    finally:
        await purge_dashboard(did)
        await _cleanup(ids, obj)


async def test_attention_respects_row_level_access(client, admin_headers, viewer, ids):
    """Замечание не должно называть строку, которую этому человеку видеть не
    положено: RLS по строкам применяется ДО проверок."""
    obj = await _seed(ids, {"Горловка": (100, 10), "Донецк": (150, 20)})
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_att_rls"})).json()["id"]
    dep = None
    try:
        async with db.acquire() as conn:
            dep = str(await conn.fetchval(
                "insert into departments(organization_id,name) values($1,'ztest_dep_att') returning id", ids["org"]))
            await conn.execute("update users set department_id=$1::uuid where id=$2::uuid", dep, viewer["id"])
        # Зрителю разрешена только «Горловка» — про просевший «Донецк» он знать не должен.
        r = await client.put(f"/objects/{obj}/row-acl/{dep}", headers=admin_headers,
                             json={"row_labels": ["Горловка"]})
        assert r.status_code == 200, r.text

        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "P"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "K", "widget_type": "kpi",
                                "config": {"dataset_code": CODE, "value_field": "itogo"}})
        await client.post(f"/dashboards/{did}/grants", headers=admin_headers,
                          json={"grantee_type": "user", "user_id": viewer["id"]})
        await client.post(f"/dashboards/{did}/publish", headers=admin_headers)

        res = (await client.get(f"/dashboard-pages/{pid}/attention", headers=viewer["headers"])).json()
        text = " ".join(w["message"] for it in res["items"] for w in it["warnings"])
        assert "Донецк" not in text, "замечание процитировало скрытую от пользователя строку"
        # Совпадение с прошлой неделей у видимой ему строки при этом НЕ
        # замалчивается — иначе RLS превратился бы в способ спрятать проблему.
        # (Формулировка здесь «все данные», потому что видимая часть формы у
        # этого человека и есть одна строка.)
        assert res["items"] and "совпада" in text
        # И формулировка честная: «все данные» превратились бы в неправду —
        # человек с одной доступной строкой решил бы, что не обновилась вся форма.
        assert "доступные вам строки" in text
        assert "Все данные совпадают" not in text
    finally:
        await purge_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute("delete from data_row_acl where object_id=$1::uuid", obj)
            await conn.execute("update users set department_id=null where id=$1::uuid", viewer["id"])
            if dep:
                await conn.execute("delete from departments where id=$1::uuid", dep)
        await _cleanup(ids, obj)
