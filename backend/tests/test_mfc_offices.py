"""Справочник отделений МФЦ (раздел «Карта»).

Проверяются правила, которые дороже всего потерять при следующей правке:
ключ импорта, неразрушающий повторный импорт, слияние режима работы,
исключительность строки отчёта, сверка «в отчёте есть, на карте нет» и права.
"""
from __future__ import annotations

import pytest

from app import db

pytestmark = pytest.mark.asyncio(loop_scope="session")

PREFIX = "ztest_мфц"

# Шаблон в том виде, в каком его выгружает ведомство: точка с запятой, BOM,
# двойной пробел в имени, ПРОПУЩЕННАЯ запятая между «сб» и «вс» и строка без
# координат — всё это встречается в настоящем файле.
CSV = (
    "﻿id;layer_name;adress;name;telephone_1;telephone_2;mail;website;operating_mode;"
    "information;coordinates\n"
    "mfc_1;МФЦ;г. Донецк, ул. Челюскинцев, 167;" + PREFIX + "  Донецк;119;;a@b.ru;https://x;"
    "пн: 08:00 - 17:00,  вт: 08:00 - 17:00,  ср: 08:00 - 17:00,  чт: 10:00 - 19:00,  "
    "пт: 08:00 - 17:00,  сб: 08:00 - 17:00     вс: выходной;;48.009964,37.808141\n"
    "mfc_1;МФЦ;пгт Тельманово, ул. Ленина, 140;" + PREFIX + " Тельманово;119;;;;"
    "пн: 09:00 - 18:00,  сб: выходной,     вс;;47.410644,38.015625\n"
    "mfc_2;МФЦ;г. Донецк, пр-кт Киевский, 63;" + PREFIX + " без координат;119;;;;;;\n"
)


async def _cleanup():
    async with db.acquire() as conn:
        await conn.execute("delete from audit_log where entity_type='mfc_office' and entity_id in "
                           "(select id from mfc_offices where name like $1)", PREFIX + "%")
        await conn.execute("delete from mfc_offices where name like $1", PREFIX + "%")


@pytest.fixture
async def clean():
    await _cleanup()
    yield
    await _cleanup()


def _files():
    return {"file": ("offices.csv", CSV.encode("utf-8"), "text/csv")}


async def test_import_reads_template_and_does_not_overwrite_manual_edits(client, admin_headers, clean):
    """Импорт разбирает шаблон; повторный импорт НЕ трогает правки руками.

    Ключ — имя отделения: в настоящем файле `id` дублируется (у ТОСП стоит id
    головного МФЦ), и импорт по нему склеил бы разные отделения в одно.
    """
    r = await client.post("/map/offices/import", headers=admin_headers, files=_files())
    assert r.status_code == 200, r.text
    res = r.json()
    assert (res["total"], res["created"], res["skipped"]) == (3, 3, 0)
    # Обе строки с одинаковым внешним id завелись как РАЗНЫЕ отделения.
    assert res["errors"] == []
    # Отделение без координат заводится и живёт в справочнике — просто не рисуется.
    assert res["no_coords"] == [PREFIX + " без координат"]
    assert res["outside_contour"] == []

    items = (await client.get("/map/offices", headers=admin_headers, params={"q": PREFIX})).json()
    assert len(items) == 3
    donetsk = next(o for o in items if o["name"] == PREFIX + " Донецк")
    # Двойной пробел в имени схлопнут, город прочитан из адреса, точка в контуре.
    assert donetsk["city"] == "Донецк" and donetsk["inside_contour"] is True
    # Суббота РАБОЧАЯ, хотя запятой перед «вс» в файле нет: разбор режется по
    # следующему дню недели, а не по запятой.
    assert donetsk["hours"]["sat"] == {"from": "08:00", "to": "17:00"}
    assert donetsk["hours"]["sun"] is None
    # «вс» без значения — выходной, а не «неизвестно».
    telmanovo = next(o for o in items if o["name"] == PREFIX + " Тельманово")
    assert telmanovo["hours"]["sun"] is None and telmanovo["hours"]["mon"]["to"] == "18:00"

    # Правка руками → повторный импорт того же файла её не затирает.
    await client.patch(f"/map/offices/{donetsk['id']}", headers=admin_headers,
                       json={"phone": "+7 (949) 111-11-11"})
    r2 = await client.post("/map/offices/import", headers=admin_headers, files=_files())
    assert (r2.json()["created"], r2.json()["skipped"]) == (0, 3)
    after = (await client.get(f"/map/offices/{donetsk['id']}", headers=admin_headers)).json()
    assert after["phone"] == "+7 (949) 111-11-11"

    # Явное обновление существующих — осознанный выбор, и оно возвращает файл.
    r3 = await client.post("/map/offices/import", headers=admin_headers,
                           files=_files(), params={"update_existing": "true"})
    assert r3.json()["updated"] == 3
    assert (await client.get(f"/map/offices/{donetsk['id']}", headers=admin_headers)).json()["phone"] == "119"


async def test_changing_one_day_keeps_the_rest_of_the_week(client, admin_headers, clean):
    """Правка одного дня не стирает остальные шесть.

    Типовое изменение — «суббота стала выходной»; замена набора целиком делала
    бы неделю пустой молча, и на карте отделение выглядело бы закрытым.
    """
    await client.post("/map/offices/import", headers=admin_headers, files=_files())
    oid = next(o["id"] for o in (await client.get("/map/offices", headers=admin_headers,
                                                  params={"q": PREFIX + " Донецк"})).json())
    r = await client.patch(f"/map/offices/{oid}", headers=admin_headers, json={"hours": {"sat": None}})
    hours = r.json()["hours"]
    assert hours["sat"] is None
    assert hours["mon"] == {"from": "08:00", "to": "17:00"}
    assert len([k for k, v in hours.items() if v]) == 5

    # Время принимается только как чч:мм — иначе на карту уедет строка, которую
    # нечем показать по дням.
    bad = await client.patch(f"/map/offices/{oid}", headers=admin_headers,
                             json={"hours": {"mon": {"from": "8 утра", "to": "17:00"}}})
    assert bad.status_code == 400 and "чч:мм" in bad.json()["detail"]


async def test_one_report_row_belongs_to_one_office(client, admin_headers, clean):
    """Строка отчёта не может быть связана с двумя отделениями: иначе её
    нагрузка показалась бы дважды, в двух точках карты."""
    await client.post("/map/offices/import", headers=admin_headers, files=_files())
    items = (await client.get("/map/offices", headers=admin_headers, params={"q": PREFIX})).json()
    a, b = items[0]["id"], items[1]["id"]
    row = "ztest_строка отчёта"

    assert (await client.patch(f"/map/offices/{a}", headers=admin_headers,
                               json={"row_label": row})).status_code == 200
    busy = await client.patch(f"/map/offices/{b}", headers=admin_headers, json={"row_label": row})
    assert busy.status_code == 400 and "уже связана" in busy.json()["detail"]

    # Освободили — можно связать с другим (отделение переехало/переименовано).
    await client.patch(f"/map/offices/{a}", headers=admin_headers, json={"row_label": None})
    assert (await client.patch(f"/map/offices/{b}", headers=admin_headers,
                               json={"row_label": row})).status_code == 200


async def test_report_row_without_office_is_surfaced(client, admin_headers, seed_dataset, clean):
    """Сверка «в отчёте есть, на карте нет» — иначе новое отделение попадает в
    цифры, но не на карту, и заметить это можно только случайно."""
    await client.post("/map/offices", headers=admin_headers,
                      json={"name": PREFIX + " Паспорт", "address": "г. Донецк, ул. Паспорт, 1"})
    r = await client.get("/map/offices/unmatched", headers=admin_headers,
                         params={"dataset_code": "t_ds"})
    assert r.status_code == 200, r.text
    data = r.json()
    rows = {u["row_label"]: u for u in data["unmatched"]}
    assert "Паспорт" in rows, data
    # Подсказка находит похожее отделение по словам имени и адреса.
    assert rows["Паспорт"]["suggestion"]["name"] == PREFIX + " Паспорт"
    linked_before = data["linked"]

    # Связали — строка уходит из списка несопоставленных.
    oid = rows["Паспорт"]["suggestion"]["id"]
    await client.patch(f"/map/offices/{oid}", headers=admin_headers, json={"row_label": "Паспорт"})
    after = (await client.get("/map/offices/unmatched", headers=admin_headers,
                              params={"dataset_code": "t_ds"})).json()
    assert "Паспорт" not in {u["row_label"] for u in after["unmatched"]}
    assert after["linked"] == linked_before + 1

    # Несуществующий набор данных — понятный отказ, а не пустой экран.
    assert (await client.get("/map/offices/unmatched", headers=admin_headers,
                             params={"dataset_code": "нет-такого"})).status_code == 404


async def test_viewer_reads_but_does_not_edit(client, admin_headers, viewer, clean):
    """Сведения об отделении нужны обычному пользователю — ради него карта и
    заводится. Правка и сверка со строками отчёта — управляющим."""
    await client.post("/map/offices", headers=admin_headers, json={"name": PREFIX + " просмотр"})
    assert (await client.get("/map/offices", headers=viewer["headers"])).status_code == 200
    assert (await client.get("/map/geo/contour", headers=viewer["headers"])).status_code == 200
    assert (await client.post("/map/offices", headers=viewer["headers"],
                              json={"name": PREFIX + " чужое"})).status_code == 403
    assert (await client.get("/map/offices/unmatched", headers=viewer["headers"],
                             params={"dataset_code": "t_ds"})).status_code == 403


async def test_office_outside_contour_is_flagged_not_blocked(client, admin_headers, clean):
    """Точка вне контура помечается, но не запрещается: на самой границе
    справочная геометрия может расходиться с реальностью, а запрет остановил бы
    работу. Промах при этом виден сразу."""
    r = await client.post("/map/offices", headers=admin_headers,
                          json={"name": PREFIX + " мимо", "lat": 55.75, "lon": 37.62})
    assert r.status_code == 201 and r.json()["inside_contour"] is False
    ok = await client.post("/map/offices", headers=admin_headers,
                           json={"name": PREFIX + " внутри", "lat": 48.009964, "lon": 37.808141})
    assert ok.json()["inside_contour"] is True
    # Одна координата без пары — отказ: точка без второй половины бессмысленна.
    half = await client.post("/map/offices", headers=admin_headers,
                             json={"name": PREFIX + " половина", "lat": 48.0})
    assert half.status_code == 400

def test_tosp_is_never_suggested_as_the_head_office():
    """Обособленное подразделение (ТОСП) не сопоставляется с головным.

    В отчёте у ТОСП стоит адрес ГОЛОВНОГО отделения, поэтому по словам адреса
    он перетягивается к нему — а это чужая точка на карте и чужая нагрузка.
    Правило проверяется на настоящих строках отчёта РЦО и справочника.
    """
    from app.modules.map.service import suggest_office

    offices = [
        {"id": "1", "name": "МФЦ по городу Волноваха", "address": "г. Волноваха, ул. Ленина, 88"},
        {"id": "2", "name": "ТОСП с. Красная Поляна МФЦ г. Волноваха",
         "address": "с. Красная Поляна, ул. Григория Балжи, 60"},
    ]
    tosp_row = 'ТОСП в с. Красная Поляна Отделения ГБУ "МФЦ ДНР" г. Волноваха, ул. Ленина, 88'
    head_row = 'Отделение ГБУ "МФЦ ДНР" г. Волноваха, ул. Ленина, 88'

    assert suggest_office(tosp_row, offices)["id"] == "2"
    assert suggest_office(head_row, offices)["id"] == "1"
    # Головного в справочнике нет вовсе — молчим, а не предлагаем ТОСП.
    assert suggest_office(head_row, [offices[1]]) is None


def test_ambiguous_match_gets_no_suggestion():
    """Если одинаково похожи двое — подсказки нет: она сбила бы с толку сильнее,
    чем её отсутствие, потому что человек доверится первой попавшейся."""
    from app.modules.map.service import suggest_office

    twins = [
        {"id": "1", "name": "МФЦ Горловка", "address": "г. Горловка, ул. Ленина, 1"},
        {"id": "2", "name": "МФЦ Горловка", "address": "г. Горловка, ул. Ленина, 1"},
    ]
    assert suggest_office('Отделение ГБУ "МФЦ ДНР" г. Горловка ул. Ленина, 1', twins) is None
