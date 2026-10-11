"""Эталонные названия отделений (миграция 063, `map/office_names`).

Держится на четырёх правилах, и тесты держат именно их:
незнакомое название молча не подменяется; ТОСП не путается с головным;
подсказка только однозначная; подмена никогда не склеивает две строки.
"""
from __future__ import annotations

import json

import pytest

from app import db
from app.modules.ingestion import mapping
from app.modules.map import office_names as on

pytestmark = pytest.mark.asyncio(loop_scope="session")

PREFIX = "ztest_эталон"
CANON_CODE = "ztest_names_canon"
VARIANT_CODE = "ztest_names_variant"

# Эталонные строки — как в ежедневном отчёте; варианты — как в форме «Время».
OFFICES = [
    (PREFIX + " МФЦ №1 по городу Зтестовск", 'Отделение № 1 ГБУ "МФЦ ДНР" г. Зтестовск ул.Ленина, 1',
     "Отделение МФЦ № 1 г. Зтестовск"),
    (PREFIX + " МФЦ по городу Зтестополь", 'Отделение ГБУ "МФЦ ДНР" г. Зтестополь ул.Мира, 2',
     "Отделение МФЦ г. Зтестополь"),
    (PREFIX + " ТОСП пгт Зтестовка МФЦ г. Зтестополь",
     'ТОСП пгт. Зтестовка Отделение ГБУ "МФЦ ДНР" г. Зтестополь ул.Мира, 2',
     "ТОСП в пгт Зтестовка Отделения МФЦ г. Зтестополь"),
]


# --- Разбор и подсказка (без базы) -----------------------------------------

def _offs(*pairs):
    out = []
    for i, (name, row) in enumerate(pairs):
        o = {"id": f"o{i}", "name": name, "row_label": row}
        o["_keys"] = on.office_keys(o)
        out.append(o)
    return out


def test_parse_reads_number_type_and_settlements_in_real_spellings():
    p = on.parse_label('Отделение № 11 ГБУ " МФЦ ДНР" г, Донецк, ул. Петровского, 254')
    assert p == {"tosp": False, "num": 11, "locs": ["донецк"]}
    # «г.Донецк» без пробела, «пгт.» с точкой, «по городу» в имени справочника.
    assert on.parse_label('ТОСП ГБУ "МФЦ ДНР" г.Донецк, бул.Пушкина')["locs"] == ["донецк"]
    assert on.parse_label("ТОСП пгт. Северное Отделения №1 г. Снежное")["locs"] == ["северное", "снежное"]
    assert on.parse_label("МФЦ №3 по городу Мариуполь")["locs"] == ["мариуполь"]
    # «пгт» содержит «г», а «городу» начинается с «г» — ни то ни другое не пометка.
    assert on.parse_label("Отделение МФЦ пгт Мангуш")["locs"] == ["мангуш"]
    assert on.parse_label(".") is None


def test_tosp_never_goes_to_the_head_office_and_back():
    offices = _offs(("МФЦ по городу Енакиево", 'Отделение ГБУ "МФЦ ДНР" г. Енакиево'),
                    ("ТОСП пгт. Карло-Марксово МФЦ г. Енакиево",
                     'ТОСП пгт. Карло Марксово Отделение ГБУ "МФЦ ДНР" г. Енакиево'))
    assert on.suggest("ТОСП в пгт Карло-Марксово Отделения МФЦ г. Енакиево", offices)["office_id"] == "o1"
    assert on.suggest("Отделение МФЦ г. Енакиево", offices)["office_id"] == "o0"


def test_doubtful_names_get_no_suggestion():
    offices = _offs(("ТОСП г. Донецк МФЦ №3 г. Донецк", "ТОСП ГБУ г.Донецк, бул.Пушкина, 34"),
                    ("ТОСП г. Донецк МФЦ №9 г. Донецк", "ТОСП в г. Донецк Отделения № 9 г. Донецк"),
                    ("МФЦ №7 по городу Донецк", "Отделение № 7 г. Донецк"))
    # Без номера подходят оба ТОСП Донецка — подсказки нет.
    assert on.suggest("ТОСП г.Донецк, пр-кт Дзержинского,13", offices) is None
    # Номера нет в справочнике — подсказки нет, а не «ближайшее».
    assert on.suggest("ТОСП в г. Донецк Отделения МФЦ № 4 г. Донецк", offices) is None
    # Головное без номера к «№ 7» не подходит: номер — часть имени.
    assert on.suggest("Отделение МФЦ г. Донецк", offices) is None
    assert on.suggest("Отделение МФЦ № 7 г. Донецк", offices)["office_id"] == "o2"


def test_canonicalize_never_glues_two_rows_into_one_office():
    aliases = {on.label_key("Вариант А"): "Эталон", on.label_key("Вариант Б"): "Эталон",
               on.label_key("Вариант В"): "Эталон 2"}
    # Эталон уже есть в том же наборе — вариант остаётся.
    vals = [(0, "Эталон 2", "f", None, 1, None), (1, "Вариант В", "f", None, 2, None)]
    assert on.canonicalize(vals, aliases) == vals
    # Два варианта одного отделения в одном наборе — оба остаются.
    vals = [(0, "Вариант А", "f", None, 1, None), (1, "Вариант Б", "f", None, 2, None)]
    assert on.canonicalize(vals, aliases) == vals
    # Обычный случай: регистр и пробелы не мешают узнать вариант.
    vals = [(0, "вариант   а", "f", None, 1, None)]
    assert on.canonicalize(vals, aliases) == [(0, "Эталон", "f", None, 1, None)]


def test_sheet_values_applies_remembered_names():
    """Подмена — внутри общей `sheet_values`: тогда и сверка «изменился ли
    лист» видит те же названия, что лежат в базе."""
    table = {"data": json.dumps([["Отделение", "Принято"], ["Вариант А", "5"]]),
             "merges": None, "data_rect": None, "header_rows": 1}
    fields = [{"column_index": 0, "field_code": "name", "data_type": "text", "is_row_label": True},
              {"column_index": 1, "field_code": "prinyato", "data_type": "number", "is_row_label": False}]
    plain = mapping.sheet_values(table, layout=None, fields=fields)
    assert plain["values"][0][1] == "Вариант А"
    sv = mapping.sheet_values(table, layout=None, fields=fields,
                              aliases={on.label_key("Вариант А"): "Эталон"})
    assert sv["values"][0][1] == "Эталон"


# --- На базе ----------------------------------------------------------------

async def _cleanup(conn, org):
    await conn.execute("delete from office_name_aliases where organization_id=$1 and "
                       "(label like '%Зтест%' or label='ztest .')", org)
    await conn.execute("delete from audit_log where entity_type in ('mfc_office','office_alias') and "
                       "(new_data::text like '%Зтест%' or old_data::text like '%Зтест%')")
    await conn.execute("delete from dataset_values where dataset_release_id in "
                       "(select id from dataset_releases where code = any($1::text[]))",
                       [CANON_CODE, VARIANT_CODE])
    await conn.execute("delete from dataset_releases where code = any($1::text[])", [CANON_CODE, VARIANT_CODE])
    await conn.execute("delete from mfc_offices where name like $1", PREFIX + "%")
    await conn.execute("delete from notification_events where event_type='data.office_names' "
                       "and payload->>'code' = $1", VARIANT_CODE)


async def _release(conn, ids, obj, code, day, rows):
    rel = await conn.fetchval(
        "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,created_by,object_id) "
        "values($1,$2,'Тест названий','released',$3::text::date,$4,$5) returning id",
        ids["org"], code, day, ids["admin"], obj)
    for i, (label, v) in enumerate(rows):
        await conn.execute(
            "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
            "values($1,$2,$3,'ztest_wait',$4)", rel, i, label, v)
    return rel


@pytest.fixture
async def names_world(ids, seed_dataset):
    async with db.acquire() as conn:
        await _cleanup(conn, ids["org"])
        obj = await conn.fetchval("select id from objects where name='t_obj' and organization_id=$1", ids["org"])
        for name, canon, _ in OFFICES:
            await conn.execute("insert into mfc_offices(organization_id, name, row_label) values($1,$2,$3)",
                               ids["org"], name, canon)
        await _release(conn, ids, obj, CANON_CODE, "2026-03-01", [(o[1], 10) for o in OFFICES])
        rels = [await _release(conn, ids, obj, VARIANT_CODE, day,
                               [(o[2], 1 + i) for i, o in enumerate(OFFICES)] + [("ztest .", 0)])
                for day in ("2026-03-01", "2026-03-02")]
    yield {"obj": obj, "rels": rels}
    async with db.acquire() as conn:
        await _cleanup(conn, ids["org"])


async def _labels(code):
    async with db.acquire() as conn:
        return {r["row_label"] for r in await conn.fetch(
            "select distinct dv.row_label from dataset_values dv join dataset_releases dr "
            "on dr.id=dv.dataset_release_id where dr.code=$1", code)}


async def test_review_suggests_and_confirm_renames_history(client, admin_headers, names_world):
    r = await client.get("/map/office-names", headers=admin_headers)
    assert r.status_code == 200, r.text
    mine = {i["label"]: i for i in r.json()["items"] if "Зтест" in i["label"] or i["label"] == "ztest ."}
    assert {o[2] for o in OFFICES} <= set(mine)
    assert all(mine[o[2]]["suggestion"] for o in OFFICES)
    assert mine["ztest ."]["suggestion"] is None

    async with db.acquire() as conn:
        before = await conn.fetchval(
            "select sum(value_number) from dataset_values dv join dataset_releases dr "
            "on dr.id=dv.dataset_release_id where dr.code=$1", VARIANT_CODE)
    r = await client.post("/map/office-names/confirm-suggested", headers=admin_headers)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["conflicts"] == [] and res["errors"] == []
    assert "ztest ." in res["left_manual"]
    # Вся история формы переименована, числа не тронуты.
    assert await _labels(VARIANT_CODE) == {o[1] for o in OFFICES} | {"ztest ."}
    async with db.acquire() as conn:
        after = await conn.fetchval(
            "select sum(value_number) from dataset_values dv join dataset_releases dr "
            "on dr.id=dv.dataset_release_id where dr.code=$1", VARIANT_CODE)
    assert after == before

    # Повтор ничего не делает; «это не отделение» больше не спрашивается.
    again = (await client.post("/map/office-names/confirm-suggested", headers=admin_headers)).json()
    assert again["aliased"] == [] and again["renamed_values"] == 0
    r = await client.post("/map/office-names/confirm", headers=admin_headers,
                          json={"items": [{"label": "ztest .", "office_id": None}]})
    assert r.status_code == 200 and r.json()["ignored"] == ["ztest ."]
    labels = {i["label"] for i in (await client.get("/map/office-names", headers=admin_headers)).json()["items"]}
    assert "ztest ." not in labels


async def test_rename_skips_a_release_where_the_canon_is_already_present(client, admin_headers, ids, names_world):
    """В выпуске уже есть эталон — вариант НЕ переименовывается и выпуск
    назван: иначе одно отделение встало бы дважды и его цифры сложились бы."""
    canon, variant = OFFICES[0][1], OFFICES[0][2]
    async with db.acquire() as conn:
        mixed = await _release(conn, ids, names_world["obj"], VARIANT_CODE, "2026-03-03",
                               [(canon, 5), (variant, 7)])
        office_id = await conn.fetchval("select id::text from mfc_offices where name=$1", OFFICES[0][0])
    r = await client.post("/map/office-names/confirm", headers=admin_headers,
                          json={"items": [{"label": variant, "office_id": office_id}]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert [c["period"] for c in res["conflicts"]] == ["2026-03-03"]
    assert res["renamed_releases"] == 2
    async with db.acquire() as conn:
        left = await conn.fetch("select row_label, value_number from dataset_values "
                                "where dataset_release_id=$1 order by row_index", mixed)
    assert [(x["row_label"], float(x["value_number"])) for x in left] == [(canon, 5.0), (variant, 7.0)]


async def test_after_release_notifies_once_per_name(ids, names_world):
    async with db.acquire() as conn:
        first = await on.after_release(conn, ids["org"], VARIANT_CODE, names_world["rels"][0], names_world["obj"])
        second = await on.after_release(conn, ids["org"], VARIANT_CODE, names_world["rels"][1], names_world["obj"])
        events = await conn.fetchval("select count(*) from notification_events where event_type='data.office_names' "
                                     "and payload->>'code'=$1", VARIANT_CODE)
    assert first and first["count"] == len(OFFICES) + 1 and first["with_suggestion"] == len(OFFICES)
    assert second is None
    assert events == 1


async def test_after_release_is_silent_for_forms_that_are_not_about_offices(ids, seed_dataset):
    """Реестр, сводка, строки «Паспорт / ИНН» — не отделения, и спрашивать о
    них значило бы приучить не читать уведомление."""
    async with db.acquire() as conn:
        rel = await conn.fetchval("select id from dataset_releases where code='t_ds' order by reporting_period_start desc limit 1")
        assert await on.after_release(conn, ids["org"], "t_ds", rel) is None


async def test_names_are_closed_for_viewer(client, viewer, names_world):
    assert (await client.get("/map/office-names", headers=viewer["headers"])).status_code == 403
    assert (await client.post("/map/office-names/confirm-suggested", headers=viewer["headers"])).status_code == 403
