"""Показатели списком: столбцы формы — строками.

Единственный разрез, которого в системе не было. Все прежние списочные виды
(рейтинг, светофор, мини-графики, матрица по строкам) строятся ПО СТРОКАМ, и
внутри одного отделения схлопываются в одну строку — проверено на живых данных.
А в формах РЦО и «Статистики услуг» услуги лежат в СТОЛБЦАХ: 337 и 707 граф.

Главное, что здесь проверяется, — не «список отрисовался», а доля: на
разнородном списке её быть НЕ должно, а на однородном графа-итог не должна
попадать в базу и раздувать знаменатель.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db

CODE = "zfl_ds"
# Имена как в форме РЦО: «Ведомство · Услуга · Показатель». Итог по каждому
# показателю равен сумме остальных — ровно как в настоящей форме.
FIELDS = {
    "itogo_acc": ("ИТОГО · Принято, ед.", {"Горловка": 100.0, "Донецк": 60.0}),
    "zags_acc": ("ЗАГС (377) · Принято, ед.", {"Горловка": 70.0, "Донецк": 40.0}),
    "mvd_acc": ("МВД · Паспорт · Принято, ед.", {"Горловка": 30.0, "Донецк": 20.0}),
    "itogo_iss": ("ИТОГО · Выдано, ед.", {"Горловка": 90.0, "Донецк": 55.0}),
    "dead_acc": ("ФНС · Патент · Принято, ед.", {"Горловка": 0.0, "Донецк": 0.0}),
}
PERIODS = ["2026-07-01", "2026-07-08"]


@pytest.fixture
async def fl_ds(ids):
    """Два выпуска: во втором Горловка выросла, чтобы был прирост."""
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_releases where code=$1", CODE)
        await conn.execute("delete from objects where name=$1 and organization_id=$2",
                           "zfl_obj", ids["org"])
        obj = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'zfl_obj') returning id",
            ids["org"])
        for code, (name, _v) in FIELDS.items():
            await conn.execute(
                "insert into canonical_fields(object_id,code,name,data_type) "
                "values($1,$2,$3,'number')", obj, code, name)
        for pi, period in enumerate(PERIODS):
            rel = await conn.fetchval(
                "insert into dataset_releases(organization_id,code,name,status,"
                "reporting_period_start,created_by,object_id) "
                "values($1,$2,'Список',$3,$4::text::date,$5,$6) returning id",
                ids["org"], CODE, "released", period, ids["admin"], obj)
            for code, (_n, vals) in FIELDS.items():
                await conn.execute(
                    "insert into dataset_release_fields(dataset_release_id,canonical_field_code) "
                    "values($1,$2)", rel, code)
                for ri, (label, v) in enumerate(vals.items()):
                    # Во втором выпуске всё вдвое больше — прирост заведомо есть.
                    await conn.execute(
                        "insert into dataset_values(dataset_release_id,row_index,row_label,"
                        "canonical_field_code,value_number) values($1,$2,$3,$4,$5)",
                        rel, ri, label, code, v * (2 if pi else 1))
    yield CODE
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_releases where code=$1", CODE)
        await conn.execute("delete from canonical_fields where object_id in "
                           "(select id from objects where name='zfl_obj')")
        await conn.execute("delete from objects where name='zfl_obj'")


async def _page(client, headers, name):
    did = (await client.post("/dashboards", headers=headers, json={"name": name})).json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=headers,
                             json={"name": "Стр"})).json()["id"]
    return did, pid


async def _cleanup(did):
    async with db.acquire() as conn:
        await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
        await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
        await conn.execute("delete from dashboards where id=$1::uuid", did)


async def _data(client, headers, pid, cfg, q="", name="Список"):
    r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=headers,
                          json={"name": name, "widget_type": "field_list", "config": cfg})
    assert r.status_code == 201, r.text
    return (await client.get(f"/widgets/{r.json()['id']}/data{q}", headers=headers)).json()


ACC = ["itogo_acc", "zags_acc", "mvd_acc", "dead_acc"]


async def test_columns_become_rows(client, admin_headers, fl_ds):
    """Столбцы формы идут строками, строки формы свёрнуты суммой."""
    did, pid = await _page(client, admin_headers, "zfl_basic")
    try:
        d = await _data(client, admin_headers, pid,
                        {"dataset_code": fl_ds, "group_sep": " · ", "value_fields": ACC})
        assert d["type"] == "field_list"
        by = {r["field"]: r for r in d["rows"]}
        # Второй выпуск: Горловка 140 + Донецк 80 = 220.
        assert by["zags_acc"]["value"] == 220.0
        assert by["zags_acc"]["group"] == "ЗАГС (377)"
    finally:
        await _cleanup(did)


async def test_share_is_not_shown_for_a_mixed_list(client, admin_headers, fl_ds):
    """🔴 Принято и выдано в одном списке — доли быть не должно.

    Это две стадии ОДНОГО обращения: заявление приняли, по нему же выдали
    результат. Доля от их суммы считает обращение дважды. Найдено живой
    проверкой на данных РЦО.
    """
    did, pid = await _page(client, admin_headers, "zfl_mixed")
    try:
        d = await _data(client, admin_headers, pid,
                        {"dataset_code": fl_ds, "group_sep": " · "})   # все графы
        assert all(r["share"] is None for r in d["rows"]), "доля на смеси показателей недопустима"
        assert d["share_note"], "и причина должна быть названа словами"
        assert "складывать" in d["share_note"]
    finally:
        await _cleanup(did)


async def test_total_column_is_found_by_arithmetic_not_by_name(client, admin_headers, fl_ds):
    """🔴 Графа-итог не должна попадать в базу доли.

    Ищем её РАВЕНСТВОМ сумме остальных, а не по слову «ИТОГО» в названии: тем
    же приёмом, что проверка «сумма по строкам против строки Итого». Название
    в форме могут поменять, арифметику — нет. На «Статистике услуг» имена
    устроены иначе, и разбор по слову там бы не сработал.
    """
    did, pid = await _page(client, admin_headers, "zfl_total")
    try:
        d = await _data(client, admin_headers, pid,
                        {"dataset_code": fl_ds, "group_sep": " · ", "value_fields": ACC})
        by = {r["field"]: r for r in d["rows"]}
        assert d["has_total_row"] is True
        assert by["itogo_acc"]["is_total"] is True
        assert by["itogo_acc"]["share"] is None, "итог не занимает долю в самом себе"
        # База — сумма БЕЗ итога: 220 + 100 = 320, а не 640.
        assert d["total"] == 320.0
        # 220/320 и 100/320. Сравниваем с допуском, а не с округлённым до
        # десятой: 31,25 округляется к чётному в 31,2, и тест ловил бы правило
        # округления Python, а не долю.
        assert by["zags_acc"]["share"] == pytest.approx(68.75)
        assert by["mvd_acc"]["share"] == pytest.approx(31.25)
        assert by["zags_acc"]["share"] + by["mvd_acc"]["share"] == pytest.approx(100.0)
    finally:
        await _cleanup(did)


async def test_empty_indicators_are_hidden_but_counted(client, admin_headers, fl_ds):
    """Пустые графы не показываются, но их число названо — молча не пропадают."""
    did, pid = await _page(client, admin_headers, "zfl_zero")
    try:
        d = await _data(client, admin_headers, pid,
                        {"dataset_code": fl_ds, "group_sep": " · ", "value_fields": ACC})
        assert "dead_acc" not in {r["field"] for r in d["rows"]}
        assert d["zero_hidden"] == 1

        full = await _data(client, admin_headers, pid,
                           {"dataset_code": fl_ds, "group_sep": " · ",
                            "value_fields": ACC, "hide_zero": False}, name="Со всеми")
        assert "dead_acc" in {r["field"] for r in full["rows"]}
        assert full["zero_hidden"] == 0
    finally:
        await _cleanup(did)


async def test_works_inside_a_single_row(client, admin_headers, fl_ds):
    """Ради этого вид и заводился: внутри ОДНОГО отделения.

    Прежние списочные виды строятся по строкам и здесь схлопываются в одну
    строку — на живых данных проверено, что от них остаётся один ряд.
    """
    did, pid = await _page(client, admin_headers, "zfl_row")
    try:
        d = await _data(client, admin_headers, pid,
                        {"dataset_code": fl_ds, "group_sep": " · ", "value_fields": ACC},
                        q="?row=" + "%D0%93%D0%BE%D1%80%D0%BB%D0%BE%D0%B2%D0%BA%D0%B0")
        by = {r["field"]: r for r in d["rows"]}
        assert by["zags_acc"]["value"] == 140.0, "только Горловка, без Донецка"
        assert by["mvd_acc"]["value"] == 60.0
        assert len(d["rows"]) == 3, "три непустые графы этого отделения"
    finally:
        await _cleanup(did)


async def test_growth_is_measured_against_the_previous_report(client, admin_headers, fl_ds):
    """Прирост к прошлому отчёту, и процент от нуля не считается."""
    did, pid = await _page(client, admin_headers, "zfl_delta")
    try:
        d = await _data(client, admin_headers, pid,
                        {"dataset_code": fl_ds, "group_sep": " · ",
                         "value_fields": ACC, "hide_zero": False})
        by = {r["field"]: r for r in d["rows"]}
        assert d["prev_period"] == "2026-07-01"
        assert by["zags_acc"]["prev"] == 110.0 and by["zags_acc"]["delta"] == 110.0
        assert round(by["zags_acc"]["delta_pct"]) == 100
        # Графа, которая и была нулём, и осталась нулём: процента от нуля нет.
        assert by["dead_acc"]["delta"] == 0.0
        assert by["dead_acc"]["delta_pct"] is None
    finally:
        await _cleanup(did)
