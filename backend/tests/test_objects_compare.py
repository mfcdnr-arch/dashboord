"""Сравнение подразделений: период, права на строки, доли и честное молчание.

🔴 Три дефекта, найденные живым осмотром 09.09, и все молчаливые: фильтр
периода не действовал вовсе (обёртка сводит диапазон к выпуску по
`dataset_code`, а у этого вида его нет), права на строки не применялись
(`allowed` считается только при заданном `dataset_code`), доли складывались.

Четвёртая беда была не в расчёте, а в подаче: показатель находится ровно у
одного объекта — коды граф выводятся из заголовков КОНКРЕТНОЙ формы, — и
виджет рисовал одинокий столбик, который читается как «у остальных ноль».
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db

# Два подразделения сдают ОДНУ форму, поэтому код графы у них общий — ровно тот
# случай, ради которого вид и заводился.
CODE_A, CODE_B = "zoc_a", "zoc_b"
# Коды с префиксом: короткие имена вроде `prinyato` уже заняты настоящими
# данными стенда (у МВД), и тест зацепил бы чужой объект.
FIELDS = {"zoc_prinyato": "Принято, ед.", "zoc_dolya": "Доля обращений, %"}
PERIODS = ["2026-07-10", "2026-08-10"]
# {объект: {период: {поле: {строка: значение}}}}
DATA = {
    "zoc_obj_a": {"2026-07-10": {"zoc_prinyato": {"Горловка": 100.0, "Донецк": 50.0},
                                 "zoc_dolya": {"Горловка": 40.0, "Донецк": 60.0}},
                  "2026-08-10": {"zoc_prinyato": {"Горловка": 300.0, "Донецк": 200.0},
                                 "zoc_dolya": {"Горловка": 20.0, "Донецк": 80.0}}},
    "zoc_obj_b": {"2026-07-10": {"zoc_prinyato": {"Горловка": 70.0, "Донецк": 30.0},
                                 "zoc_dolya": {"Горловка": 10.0, "Донецк": 30.0}},
                  "2026-08-10": {"zoc_prinyato": {"Горловка": 90.0, "Донецк": 60.0},
                                 "zoc_dolya": {"Горловка": 50.0, "Донецк": 70.0}}},
}
OBJ_CODE = {"zoc_obj_a": CODE_A, "zoc_obj_b": CODE_B}


@pytest.fixture
async def oc_ds(ids):
    async with db.acquire() as conn:
        await _purge(conn)
        for obj_name, by_period in DATA.items():
            obj = await conn.fetchval(
                "insert into objects(organization_id,name) values($1,$2) returning id",
                ids["org"], obj_name)
            for code, nm in FIELDS.items():
                await conn.execute("insert into canonical_fields(object_id,code,name,data_type) "
                                   "values($1,$2,$3,'number')", obj, code, nm)
            for period, by_field in by_period.items():
                rel = await conn.fetchval(
                    "insert into dataset_releases(organization_id,code,name,status,"
                    "reporting_period_start,created_by,object_id) "
                    "values($1,$2,'Форма',$3,$4::text::date,$5,$6) returning id",
                    ids["org"], OBJ_CODE[obj_name], "released", period, ids["admin"], obj)
                for code, rows in by_field.items():
                    await conn.execute("insert into dataset_release_fields(dataset_release_id,"
                                       "canonical_field_code) values($1,$2)", rel, code)
                    for ri, (label, v) in enumerate(rows.items()):
                        await conn.execute(
                            "insert into dataset_values(dataset_release_id,row_index,row_label,"
                            "canonical_field_code,value_number) values($1,$2,$3,$4,$5)",
                            rel, ri, label, code, v)
    yield
    async with db.acquire() as conn:
        await _purge(conn)


async def _purge(conn):
    await conn.execute("delete from dataset_values where dataset_release_id in "
                       "(select id from dataset_releases where code = any($1::text[]))", [CODE_A, CODE_B])
    await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                       "(select id from dataset_releases where code = any($1::text[]))", [CODE_A, CODE_B])
    await conn.execute("delete from dataset_releases where code = any($1::text[])", [CODE_A, CODE_B])
    await conn.execute("delete from canonical_fields where object_id in "
                       "(select id from objects where name like 'zoc_obj_%')")
    await conn.execute("delete from objects where name like 'zoc_obj_%'")


async def _page(client, headers, name):
    # force: одноимённый дашборд от прерванного прогона иначе даёт 409 и тест
    # падает не по существу (переспрос про дубли имён живёт с 16.08).
    r = await client.post("/dashboards", headers=headers, json={"name": name, "force": True})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=headers,
                             json={"name": "Стр"})).json()["id"]
    return did, pid


async def _cleanup(did):
    async with db.acquire() as conn:
        await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
        await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
        await conn.execute("delete from dashboards where id=$1::uuid", did)


async def _widget(client, headers, pid, field):
    r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=headers,
                          json={"name": "Сравнение", "widget_type": "objects_compare",
                                "config": {"value_field": field}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _data(client, headers, wid, q=""):
    return (await client.get(f"/widgets/{wid}/data{q}", headers=headers)).json()


async def test_period_filter_picks_the_report_of_that_period(client, admin_headers, oc_ds):
    """🔴 Фильтр периода не действовал ВОВСЕ — виджет всегда показывал свежее.

    Замер на живых данных РЦО: при фильтре «июль» виджет отдавал 5 426 (цифру
    за 31.08) вместо 4 768. Прежний запрос дат не принимал вообще.
    """
    did, pid = await _page(client, admin_headers, "zoc_period")
    try:
        wid = await _widget(client, admin_headers, pid, "zoc_prinyato")
        now = await _data(client, admin_headers, wid)
        assert dict(zip(now["categories"], now["values"], strict=False)) == {
            "zoc_obj_a": 500.0, "zoc_obj_b": 150.0}
        assert now["as_of"] == "2026-08-10"

        july = await _data(client, admin_headers, wid, "?from=2026-07-01&to=2026-07-31")
        assert dict(zip(july["categories"], july["values"], strict=False)) == {
            "zoc_obj_a": 150.0, "zoc_obj_b": 100.0}
        assert july["as_of"] == "2026-07-10"

        # Период без отчётов — честное молчание, а не откат к свежим данным.
        empty = await _data(client, admin_headers, wid, "?from=2020-01-01&to=2020-12-31")
        assert empty.get("no_data_in_period") is True
        assert not empty.get("values")
    finally:
        await _cleanup(did)


async def test_shares_are_averaged_not_summed(client, admin_headers, oc_ds):
    """Доля не складывается по строкам: её итог — среднее (правило одно на систему)."""
    did, pid = await _page(client, admin_headers, "zoc_share")
    try:
        wid = await _widget(client, admin_headers, pid, "zoc_dolya")
        d = await _data(client, admin_headers, wid)
        assert d["aggregate"] == "avg"
        # Август: A (20+80)/2 = 50, B (50+70)/2 = 60 — а не 100 и 120.
        assert dict(zip(d["categories"], d["values"], strict=False)) == {
            "zoc_obj_a": 50.0, "zoc_obj_b": 60.0}
    finally:
        await _cleanup(did)


async def test_row_level_access_is_applied(client, admin_headers, viewer, ids, oc_ds):
    """🔴 Права на строки не применялись: зритель видел сумму по ВСЕМ строкам.

    Правило заводится на один датасет, поэтому у второго объекта оно не
    действует — и это верно: наборы данных у подразделений разные.
    """
    did, pid = await _page(client, admin_headers, "zoc_rls")
    async with db.acquire() as conn:
        obj_a = str(await conn.fetchval("select id from objects where name='zoc_obj_a'"))
        dep = str(await conn.fetchval(
            "insert into departments(organization_id,name) values($1,'zoc_dep') returning id", ids["org"]))
        await conn.execute("update users set department_id=$1::uuid where id=$2::uuid", dep, viewer["id"])
    try:
        wid = await _widget(client, admin_headers, pid, "zoc_prinyato")
        await client.post(f"/dashboards/{did}/publish", headers=admin_headers)
        await client.post(f"/dashboards/{did}/grants", headers=admin_headers,
                          json={"grantee_type": "user", "user_id": viewer["id"]})
        # Правило заводится на ОДИН объект — у второго данные подразделения
        # свои, и это верно: наборы данных у подразделений разные.
        r = await client.put(f"/objects/{obj_a}/row-acl/{dep}", headers=admin_headers,
                             json={"row_labels": ["Горловка"]})
        assert r.status_code == 200, r.text

        full = await _data(client, admin_headers, wid)
        assert dict(zip(full["categories"], full["values"], strict=False))["zoc_obj_a"] == 500.0

        limited = await _data(client, viewer["headers"], wid)
        by_obj = dict(zip(limited["categories"], limited["values"], strict=False))
        assert by_obj["zoc_obj_a"] == 300.0, "зрителю видна только Горловка"
        assert by_obj["zoc_obj_b"] == 150.0, "на другой объект правило не распространяется"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from data_row_acl where object_id=$1::uuid", obj_a)
            await conn.execute("update users set department_id=null where id=$1::uuid", viewer["id"])
            await conn.execute("delete from departments where name='zoc_dep'")
        await _cleanup(did)


async def test_single_object_says_why_instead_of_drawing_one_bar(client, admin_headers, oc_ds):
    """Один столбик — не сравнение; виджет называет причину, а не молчит.

    Коды граф выводятся из заголовков конкретной формы, поэтому у другого
    подразделения тот же показатель зовётся иначе — и это НЕ ноль у соседей.
    """
    did, pid = await _page(client, admin_headers, "zoc_single")
    async with db.acquire() as conn:
        # Графа только у одного объекта — ровно случай «Статистики услуг».
        obj_b = await conn.fetchval("select id from objects where name='zoc_obj_b'")
        await conn.execute("insert into canonical_fields(object_id,code,name,data_type) "
                           "values($1,'zoc_only','Только у Б, ед.','number')", obj_b)
        rel = await conn.fetchval(
            "select id from dataset_releases where code=$1 order by reporting_period_start desc limit 1", CODE_B)
        await conn.execute("insert into dataset_release_fields(dataset_release_id,"
                           "canonical_field_code) values($1,'zoc_only')", rel)
        await conn.execute("insert into dataset_values(dataset_release_id,row_index,row_label,"
                           "canonical_field_code,value_number) values($1,0,'Горловка','zoc_only',7.0)", rel)
    try:
        wid = await _widget(client, admin_headers, pid, "zoc_only")
        d = await _data(client, admin_headers, wid)
        assert d["categories"] == ["zoc_obj_b"] and d["values"] == [7.0]
        assert "сравнивать не с чем" in d["note"]
        assert "zoc_obj_b" in d["note"]

        # А там, где сравнивать есть с чем, оговорки быть не должно.
        wid2 = await _widget(client, admin_headers, pid, "zoc_prinyato")
        assert (await _data(client, admin_headers, wid2))["note"] is None
    finally:
        await _cleanup(did)


# ── Круговая: хвост складывается, а не отбрасывается ────────────────────────

async def test_pie_folds_the_tail_and_keeps_the_whole(client, admin_headers, oc_ds):
    """🔴 Круговая на 62 отделениях нечитаема, но выбрасывать строки нельзя.

    Доля считается ОТ ЦЕЛОГО: показав десять строк из шестидесяти двух, виджет
    показал бы доли от обрезка — правдоподобно и неверно. Поэтому хвост
    складывается в «Прочие», и сумма долей по-прежнему равна целому.
    """
    did, pid = await _page(client, admin_headers, "zoc_pie")
    async with db.acquire() as conn:
        rel = await conn.fetchval(
            "select id from dataset_releases where code=$1 order by reporting_period_start desc limit 1", CODE_A)
        # Двадцать мелких строк поверх двух имеющихся: как у РЦО, где хвост
        # тоньше процента каждая.
        for i in range(20):
            await conn.execute(
                "insert into dataset_values(dataset_release_id,row_index,row_label,"
                "canonical_field_code,value_number) values($1,$2,$3,'zoc_prinyato',$4)",
                rel, 10 + i, f"Мелкое {i}", 1.0)
    try:
        r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                              json={"name": "Круговая", "widget_type": "pie",
                                    "config": {"dataset_code": CODE_A, "value_field": "zoc_prinyato"}})
        d = (await client.get(f"/widgets/{r.json()['id']}/data", headers=admin_headers)).json()

        assert len(d["categories"]) == 8, "семь секторов плюс «Прочие»"
        assert d["categories"][-1].startswith("Прочие (")
        assert d["hidden_rows"] == 15 and d["total_rows"] == 22
        # Главное: целое не изменилось — 300 + 200 + 20 мелких.
        assert sum(d["values"]) == 520.0
        # Крупнейшие остались на месте и не уехали в «Прочие».
        assert 300.0 in d["values"] and 200.0 in d["values"]

        # Короткий список не трогаем вовсе.
        r2 = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                               json={"name": "Круговая Б", "widget_type": "pie",
                                     "config": {"dataset_code": CODE_B, "value_field": "zoc_prinyato"}})
        d2 = (await client.get(f"/widgets/{r2.json()['id']}/data", headers=admin_headers)).json()
        assert len(d2["categories"]) == 2 and d2.get("hidden_rows") is None
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from dataset_values where dataset_release_id=$1 "
                               "and row_label like 'Мелкое %'", rel)
        await _cleanup(did)


async def test_pie_says_when_it_cannot_answer(client, admin_headers, oc_ds):
    """Ровное распределение: «Прочие» больше половины — круговая не отвечает.

    Замер на РЦО: пятёрка крупнейших даёт 20,8 % целого, «Прочие» — 73,2 %.
    Виджет называет это словами и предлагает вид, который на таких данных
    работает, вместо круга, показывающего «почти всё в остальных».
    """
    did, pid = await _page(client, admin_headers, "zoc_pie_flat")
    async with db.acquire() as conn:
        rel = await conn.fetchval(
            "select id from dataset_releases where code=$1 order by reporting_period_start desc limit 1", CODE_B)
        for i in range(30):
            await conn.execute(
                "insert into dataset_values(dataset_release_id,row_index,row_label,"
                "canonical_field_code,value_number) values($1,$2,$3,'zoc_prinyato',$4)",
                rel, 20 + i, f"Ровное {i}", 50.0)
    try:
        r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                              json={"name": "Круговая ровная", "widget_type": "pie",
                                    "config": {"dataset_code": CODE_B, "value_field": "zoc_prinyato"}})
        d = (await client.get(f"/widgets/{r.json()['id']}/data", headers=admin_headers)).json()
        assert "Ранжированный список" in d["note"]
        assert "%" in d["note"]
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from dataset_values where dataset_release_id=$1 "
                               "and row_label like 'Ровное %'", rel)
        await _cleanup(did)
