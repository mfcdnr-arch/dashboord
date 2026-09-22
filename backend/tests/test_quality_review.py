"""Проверка качества по ВСЕЙ истории формы, а не по последнему отчёту.

Замечания к данным считаются с 15.08.2026, но показываются ровно в двух местах,
и оба смотрят на ОДИН отчёт: модератор — на тот, что выпускает, а блок «На что
посмотреть» — на последний активный. Поэтому расхождение итоговой графы,
найденное 22.09.2026 в 54 отчётах РЦО из 201, пришлось искать разовым скриптом:
в самой системе спросить «а где по истории расходится» было негде.

Своих правил здесь нет: считает та же `check_release`. Проверяется, что она
доходит до КАЖДОГО отчёта окна и что вердикт не зависит от того, какую глубину
выбрал человек.
"""
from datetime import date, timedelta

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db

CODE = "ztest_qr"
FIELDS = {
    "esia": "ЕСИА · Принято, ед.",
    "rosreestr": "Росреестр · Принято, ед.",
    "itogo": "ИТОГО · Принято, ед.",
}


async def _seed(conn, org_id, object_id, admin_id, period, rows):
    """rows: {строка: {код поля: число}}"""
    rel = await conn.fetchval(
        "insert into dataset_releases(organization_id,code,name,status,"
        "reporting_period_start,created_by,object_id) "
        "values($1,$2,'Форма РЦО','validated',$3,$4,$5) returning id",
        org_id, CODE, period, admin_id, object_id)
    vals = [(rel, i, label, code, v)
            for i, (label, cells) in enumerate(rows.items())
            for code, v in cells.items()]
    await conn.executemany(
        "insert into dataset_values(dataset_release_id,row_index,row_label,"
        "canonical_field_code,value_number) values($1,$2,$3,$4,$5)", vals)
    return rel


def _row(esia, rosreestr, itogo):
    return {"esia": esia, "rosreestr": rosreestr, "itogo": itogo}


@pytest_asyncio.fixture
async def form_history(client, admin_headers, ids):
    """Четыре отчёта; расходится ТОЛЬКО второй — то есть давно не последний."""
    r = await client.post("/objects", headers=admin_headers, json={"name": "ztest_qr_obj"})
    oid = r.json()["id"]
    async with db.acquire() as conn:
        admin_id = await conn.fetchval("select id from users where login='admin'")
        for code, name in FIELDS.items():
            await conn.execute(
                "insert into canonical_fields(object_id, code, name, data_type, created_by) "
                "values($1::uuid,$2,$3,'number',$4)", oid, code, name, admin_id)
        base = date(2026, 3, 2)
        history = [
            {"Донецк": _row(10, 5, 15), "Горловка": _row(20, 7, 27)},
            # 🔴 Итог меньше суммы услуг: потерялась услуга. Второй отчёт из
            # четырёх — по последнему такое не увидеть никогда.
            {"Донецк": _row(30, 9, 31), "Горловка": _row(41, 13, 54)},
            {"Донецк": _row(52, 17, 69), "Горловка": _row(63, 23, 86)},
            {"Донецк": _row(74, 29, 103), "Горловка": _row(85, 31, 116)},
        ]
        for i, rows in enumerate(history):
            await _seed(conn, ids["org"], oid, admin_id, base + timedelta(days=7 * i), rows)
    yield {"object_id": oid, "org": ids["org"]}
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_releases where code=$1", CODE)
        await conn.execute("delete from canonical_fields where object_id=$1::uuid", oid)
        await conn.execute("delete from objects where id=$1::uuid", oid)


async def test_review_finds_a_defect_in_an_old_report(client, admin_headers, form_history):
    """Расхождение в СТАРОМ отчёте найдено — ради этого проверка и заводилась."""
    r = await client.get(f"/objects/{form_history['object_id']}/quality-review",
                         headers=admin_headers)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["checked"] == 4 and res["total"] == 4
    issue = next((i for i in res["issues"] if i["code"] == "total_column_mismatch"), None)
    assert issue is not None, res["issues"]
    assert issue["periods"] == ["2026-03-09"], issue
    assert "Донецк" in issue["example"] or "Горловка" in issue["example"], issue
    # Остальные три отчёта чистые — иначе свод «где расходится» не сужает поиск.
    assert res["clean"] == 3, res


async def test_latest_report_alone_would_have_missed_it(client, admin_headers, form_history):
    """Глубина в один отчёт молчит: это и есть то, что показывали до сих пор.

    Тест держит ПРИЧИНУ существования экрана. Совпади он с проверкой последнего
    отчёта — экран был бы лишним.
    """
    r = await client.get(f"/objects/{form_history['object_id']}/quality-review?limit=1",
                         headers=admin_headers)
    res = r.json()
    assert res["checked"] == 1 and res["total"] == 4, res
    assert not [i for i in res["issues"] if i["code"] == "total_column_mismatch"], res["issues"]


async def test_window_reads_its_own_predecessor(client, admin_headers, form_history, ids):
    """Первый отчёт окна сверяется со СВОИМ предшественником, а не «без прошлого».

    Иначе вердикт по одним и тем же данным менялся бы от выбранной глубины:
    сдвинул окно — и повторение прошлой недели перестало быть замечанием.
    """
    async with db.acquire() as conn:
        admin_id = await conn.fetchval("select id from users where login='admin'")
        # Пятый отчёт — точная копия четвёртого: данные не обновили.
        await _seed(conn, ids["org"], form_history["object_id"], admin_id,
                    date(2026, 3, 2) + timedelta(days=28),
                    {"Донецк": _row(74, 29, 103), "Горловка": _row(85, 31, 116)})
    try:
        r = await client.get(f"/objects/{form_history['object_id']}/quality-review?limit=1",
                             headers=admin_headers)
        res = r.json()
        codes = [i["code"] for i in res["issues"]]
        assert "same_as_previous" in codes, res["issues"]
    finally:
        async with db.acquire() as conn:
            await conn.execute(
                "delete from dataset_values where dataset_release_id in "
                "(select id from dataset_releases where code=$1 and reporting_period_start=$2)",
                CODE, date(2026, 3, 30))
            await conn.execute(
                "delete from dataset_releases where code=$1 and reporting_period_start=$2",
                CODE, date(2026, 3, 30))


async def test_review_is_closed_from_viewer(client, viewer, form_history):
    """Сырые данные формы — служебный слой: зрителю сюда нельзя (правка 14.09)."""
    r = await client.get(f"/objects/{form_history['object_id']}/quality-review",
                         headers=viewer["headers"])
    assert r.status_code in (403, 404), r.status_code


async def test_depth_is_capped(client, admin_headers, form_history):
    """Глубину нельзя запросить без границы: проверка читает каждый отчёт целиком."""
    r = await client.get(f"/objects/{form_history['object_id']}/quality-review?limit=100000",
                         headers=admin_headers)
    assert r.status_code == 422, r.text
