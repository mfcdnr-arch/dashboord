"""Предпросмотр «что изменится на дашбордах» перед выпуском (п. 15).

До этого модератор перед кнопкой «Выпустить» видел только замечания к самим
данным. Что от выпуска изменится на экранах у руководителей — не показывал
никто, и выпуск делался вслепую.

Тесты проверяют не наличие блока, а правильность ответов, и прежде всего —
защиту от ошибочного выпуска:

1. **Цифры считаются ТОЙ ЖЕ свёрткой, что у карточки показателя** — иначе
   предпросмотр обещал бы одно, а дашборд показал другое.
2. **Исчезнувшая графа названа, и виджеты на неё помечены** — это главная
   защита: потеря графы не выглядит ошибкой нигде больше, виджет просто
   начинает показывать «нет данных».
3. **Отчёт задним числом на дашборды не попадает** — виджет читает последний
   выпуск. Промолчать значило бы дать ложную уверенность.
4. **Закреплённый срез не меняется**, если выпускают не его период.
5. **Замещение сравнивается с замещаемым выпуском**, а не с последним.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import db, purge_dashboard

from app.modules.ingestion import impact

CODE = "ztest_imp_ds"

# Разметка так, как её отдаёт конструктор: столбец 0 — названия строк.
FIELDS = [
    {"column_index": 0, "field_code": "row", "field_name": "Строка",
     "data_type": "text", "is_row_label": True},
    {"column_index": 1, "field_code": "obr", "field_name": "Обращения",
     "data_type": "number", "is_row_label": False},
    {"column_index": 2, "field_code": "uved", "field_name": "Уведомления",
     "data_type": "number", "is_row_label": False},
]
FIELDS_NO_UVED = [f for f in FIELDS if f["field_code"] != "uved"]


async def _seed(conn, org, admin, period="2026-08-12", values=((100, 10), (200, 20))):
    obj = await conn.fetchval("select id from objects where name='ztest_imp_obj'")
    if obj is None:
        obj = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_imp_obj') returning id", org)
    rel = await conn.fetchval(
        "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,"
        "created_by,object_id) values($1,$2,'Импакт ДС','released',$3::text::date,$4,$5) returning id",
        org, CODE, period, admin, obj)
    for i, (o, u) in enumerate(values):
        for fc, v in (("obr", o), ("uved", u)):
            await conn.execute(
                "insert into dataset_values(dataset_release_id,row_index,row_label,"
                "canonical_field_code,value_number) values($1,$2,$3,$4,$5)",
                rel, i, f"Строка {i + 1}", fc, v)
    for fc, nm in (("obr", "Обращения"), ("uved", "Уведомления")):
        await conn.execute(
            "insert into canonical_fields(object_id,code,name,data_type) values($1,$2,$3,'number') "
            "on conflict do nothing", obj, fc, nm)
    return obj, rel


async def _drop(conn, org):
    await conn.execute("delete from dataset_values where dataset_release_id in "
                       "(select id from dataset_releases where code like 'ztest_imp%')")
    await conn.execute("delete from dataset_releases where code like 'ztest_imp%'")
    await conn.execute("delete from canonical_fields where object_id in "
                       "(select id from objects where name like 'ztest_imp%')")
    await conn.execute("delete from objects where name like 'ztest_imp%' and organization_id=$1", org)


@pytest.fixture
async def seeded(ids):
    async with db.acquire() as conn:
        await _drop(conn, ids["org"])
        obj, rel = await _seed(conn, ids["org"], ids["admin"])
    yield {"org": ids["org"], "admin": ids["admin"], "object_id": str(obj)}
    async with db.acquire() as conn:
        await _drop(conn, ids["org"])


async def _impact(org, *, rows, fields=None, period="2026-08-19"):
    async with db.acquire() as conn:
        return await impact.release_impact(
            conn, org, code=CODE, period=period,
            rows=rows, fields=fields or FIELDS, label_col=0)


async def test_numbers_match_what_the_card_will_show(seeded):
    """По каждой графе: сколько сейчас, сколько станет и на сколько изменится.

    Свёртка — сумма по строкам, та же, что у карточки показателя: 100+200=300
    сейчас, 150+250=400 станет.
    """
    d = await _impact(seeded["org"], rows=[["Строка 1", "150", "15"], ["Строка 2", "250", "25"]])
    obr = next(f for f in d["fields"] if f["field"] == "obr")
    assert obr["current"] == 300 and obr["next"] == 400
    assert obr["delta"] == 100
    assert round(obr["delta_pct"], 2) == 33.33
    assert obr["how"] == "sum" and obr["name"] == "Обращения"
    assert d["becomes_current"] is True
    assert d["replaces"] is None
    assert d["rows"]["current"] == 2 and d["rows"]["next"] == 2


async def test_lost_field_is_named_and_widgets_flagged(client, admin_headers, seeded):
    """🔴 Главная защита: графа исчезла — виджеты на неё помечены поимённо.

    Потеря графы не выглядит ошибкой больше нигде: выпуск пройдёт, а виджет
    молча начнёт показывать «нет данных». Здесь про это сказано ДО выпуска, и
    исчезнувшая графа названа по-человечески — её имени в новом файле уже нет,
    поэтому оно берётся из справочника.
    """
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_imp_dash"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                                 json={"name": "Обзор"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "Уведомления", "widget_type": "kpi",
                                "config": {"dataset_code": CODE, "value_field": "uved"}})
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "Обращения", "widget_type": "kpi",
                                "config": {"dataset_code": CODE, "value_field": "obr"}})

        # В новом файле графы «Уведомления» больше нет.
        d = await _impact(seeded["org"], rows=[["Строка 1", "150"], ["Строка 2", "250"]],
                          fields=FIELDS_NO_UVED)

        gone = next(f for f in d["fields"] if f["field"] == "uved")
        assert gone["gone"] is True
        assert gone["name"] == "Уведомления", "исчезнувшая графа названа по-человечески"
        assert d["lost_fields"] == ["uved"]

        at_risk = [w for w in d["widgets"] if w["at_risk"]]
        assert len(at_risk) == 1 and at_risk[0]["name"] == "Уведомления"
        assert at_risk[0]["lost_fields"] == ["uved"]
        assert at_risk[0]["dashboard"] == "ztest_imp_dash" and at_risk[0]["page"] == "Обзор"
        assert d["widgets_at_risk"] == 1

        # Второй виджет не пострадал, и у него видно «было → станет».
        ok = next(w for w in d["widgets"] if w["name"] == "Обращения")
        assert ok["at_risk"] is False
        assert ok["current"] == 300 and ok["next"] == 400 and ok["delta"] == 100
    finally:
        await purge_dashboard(did)


async def test_backdated_release_does_not_reach_dashboards(client, admin_headers, seeded):
    """Отчёт задним числом на дашборды не попадёт — и об этом сказано прямо.

    Виджет читает ПОСЛЕДНИЙ выпуск. Выпуская отчёт за более раннюю дату, легко
    решить, что цифры на экранах обновятся, — они не обновятся.
    """
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_imp_back"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                                 json={"name": "P"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "К", "widget_type": "kpi",
                                "config": {"dataset_code": CODE, "value_field": "obr"}})

        d = await _impact(seeded["org"], rows=[["Строка 1", "1", "1"]], period="2026-07-01")
        assert d["becomes_current"] is False
        assert d["latest_period"] == "2026-08-12"
        w = d["widgets"][0]
        assert w["changes"] is False
        assert "более свежий" in w["note"]
    finally:
        await purge_dashboard(did)


async def test_pinned_slice_changes_only_for_its_own_period(client, admin_headers, seeded):
    """Закреплённый срез меняется, только если выпускают ЕГО период."""
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_imp_pin"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                                 json={"name": "P"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "Срез", "widget_type": "kpi",
                                "config": {"dataset_code": CODE, "value_field": "obr",
                                           "period": "2026-08-12"}})

        # Выпускаем ДРУГОЙ период — срез не тронется.
        other = await _impact(seeded["org"], rows=[["Строка 1", "9", "9"]], period="2026-08-19")
        w = other["widgets"][0]
        assert w["changes"] is False and "закреплён за 12.08.2026" in w["note"]

        # Выпускаем ЕГО период — тронется (и это замещение).
        own = await _impact(seeded["org"], rows=[["Строка 1", "9", "9"]], period="2026-08-12")
        assert own["replaces"] is not None
        assert own["widgets"][0]["changes"] is True
    finally:
        await purge_dashboard(did)


async def test_replacing_compares_against_the_release_being_replaced(seeded):
    """Замещение сравнивается с ЗАМЕЩАЕМЫМ выпуском, а не с последним.

    Иначе при исправлении старой недели «было» бралось бы из свежего отчёта, и
    прирост показывался бы совершенно посторонний.
    """
    async with db.acquire() as conn:
        await _seed(conn, seeded["org"], seeded["admin"], period="2026-08-19",
                    values=((999, 99), (888, 88)))
    d = await _impact(seeded["org"], rows=[["Строка 1", "110", "11"], ["Строка 2", "210", "21"]],
                      period="2026-08-12")
    assert d["replaces"] is not None, "период занят — это замещение"
    obr = next(f for f in d["fields"] if f["field"] == "obr")
    assert obr["current"] == 300, "сравниваем с замещаемым выпуском (100+200), а не с 999+888"
    assert obr["next"] == 320


async def test_rows_added_and_removed_are_listed(seeded):
    """Строки, которые появились и исчезли, названы поимённо."""
    d = await _impact(seeded["org"], rows=[["Строка 1", "1", "1"], ["Горловка", "2", "2"]])
    assert d["rows"]["added"] == ["Горловка"]
    assert d["rows"]["removed"] == ["Строка 2"]
