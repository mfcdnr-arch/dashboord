"""«Паспорт цифры» (п. 17): откуда взялось это число.

Три вопроса, ради которых он есть: как графа менялась по неделям, из какого
файла пришло значение и кто его выпустил. Раньше ответ собирался по трём
экранам — «Динамика», аналитика папки и журнал.

Главное, что проверяем: паспорт объясняет ТУ цифру, которая на дашборде
(та же свёртка строк, что у карточки), и не оглашает строки, закрытые RLS.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from conftest import purge_dashboard


async def _widget(client, headers, dataset_code, field="plan", wtype="kpi"):
    did = (await client.post("/dashboards", headers=headers, json={"name": "ztest_passport"})).json()["id"]
    page = (await client.post(f"/dashboards/{did}/pages", headers=headers, json={"name": "Стр"})).json()
    w = (await client.post(f"/dashboard-pages/{page['id']}/widgets", headers=headers, json={
        "name": "Показатель", "widget_type": wtype,
        "config": {"dataset_code": dataset_code, "value_field": field}})).json()
    return did, w["id"]


async def test_history_matches_the_card_and_names_the_source(client, admin_headers, seed_dataset):
    """История по неделям: значение, прирост, файл и автор выпуска."""
    did, wid = await _widget(client, admin_headers, seed_dataset["code"])
    try:
        p = (await client.get(f"/widgets/{wid}/passport", headers=admin_headers)).json()
        assert p["field"] == "plan" and p["history"], p
        periods = [h["period"] for h in p["history"]]
        assert periods == sorted(periods), "выпуски идут по отчётной дате"
        # Значение — та же свёртка, что показывает карточка: сумма по строкам.
        last = p["history"][-1]
        assert last["value"] == float(seed_dataset["plan_sum"])
        assert last["aggregate"] == "sum" and last["rows_used"] == len(seed_dataset["rows"])
        # Прирост считается между соседними выпусками.
        assert last["delta"] == pytest.approx(
            last["value"] - p["history"][-2]["value"])
        # Кто выпустил — виден; файла у фикстуры нет (данные заведены в обход
        # конвейера), и это честное «—», а не выдуманное имя.
        assert last["released_by"], "автор выпуска обязан быть назван"
        assert "document" in last
    finally:
        await purge_dashboard(did)


async def test_row_filter_and_rls(client, admin_headers, viewer, ids, seed_dataset):
    """Паспорт по строке считает только её; закрытые строки не оглашаются."""
    did, wid = await _widget(client, admin_headers, seed_dataset["code"])
    try:
        one = (await client.get(f"/widgets/{wid}/passport?row=ИНН", headers=admin_headers)).json()
        assert one["row"] == "ИНН"
        assert one["history"][-1]["rows_used"] == 1
        assert one["history"][-1]["value"] == float(seed_dataset["plan"][1])

        # Зрителю без гранта виджет не виден — и паспорт не должен становиться
        # обходным путём к чужим данным.
        assert (await client.get(f"/widgets/{wid}/passport",
                                 headers=viewer["headers"])).status_code == 404

        # С грантом, но с RLS на строки: в свёртку идёт только разрешённая
        # строка. Правила row-level ACL заводятся на ОТДЕЛ (не на человека) —
        # так же, как в test_row_rls.
        await client.post(f"/dashboards/{did}/grants", headers=admin_headers,
                          json={"grantee_type": "user", "user_id": viewer["id"]})
        await client.post(f"/dashboards/{did}/publish", headers=admin_headers, json={})
        async with db.acquire() as conn:
            obj = str(await conn.fetchval(
                "select id from objects where name='t_obj' and organization_id=$1", ids["org"]))
            dep = str(await conn.fetchval(
                "insert into departments(organization_id,name) values($1,'ztest_dep_pass') returning id",
                ids["org"]))
            await conn.execute("update users set department_id=$1::uuid where id=$2::uuid", dep, viewer["id"])
        try:
            r = await client.put(f"/objects/{obj}/row-acl/{dep}", headers=admin_headers,
                                 json={"row_labels": ["ИНН"]})
            assert r.status_code == 200, r.text
            seen = (await client.get(f"/widgets/{wid}/passport", headers=viewer["headers"])).json()
            assert seen["history"][-1]["rows_used"] == 1, "видна только разрешённая строка"
            assert seen["history"][-1]["value"] == float(seed_dataset["plan"][1])
        finally:
            async with db.acquire() as conn:
                await conn.execute("delete from data_row_acl where object_id=$1::uuid", obj)
                await conn.execute("update users set department_id=null where id=$1::uuid", viewer["id"])
                await conn.execute("delete from departments where name='ztest_dep_pass'")
    finally:
        await purge_dashboard(did)


async def test_metric_widget_is_sent_to_the_formula_breakdown(client, admin_headers, seed_dataset):
    """У виджета по метрике происхождение — формула, и второй ответ на тот же
    вопрос здесь не выдумываем."""
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_passport_metric"})).json()["id"]
    try:
        page = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                                  json={"name": "Стр"})).json()
        w = (await client.post(f"/dashboard-pages/{page['id']}/widgets", headers=admin_headers, json={
            "name": "Текст", "widget_type": "text", "config": {"heading": "Раздел"}})).json()
        r = await client.get(f"/widgets/{w['id']}/passport", headers=admin_headers)
        assert r.status_code == 400 and "разбор" in r.json()["detail"]
    finally:
        await purge_dashboard(did)
