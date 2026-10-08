"""Незаполненная графа — не ноль (08.10.2026).

Карточка и спидометр по графе, которой в отчёте нет ни одного значения,
показывали «0»: у формы Минэкономразвития лист «Показатели» пока пуст, и
спидометр «Среднее достижение плана» стоял на «0 %» — читается как провал
плана, а лист «Сводка» того же файла в этом месте пишет «—». Ноль, вписанный
в форму, при этом обязан остаться нулём: это сведение, а не их отсутствие.
"""
from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db  # noqa: E402

CODE = "ztest_unfilled_ds"


@pytest_asyncio.fixture
async def form(ids):
    async def purge(conn):
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                           "(select id from dataset_releases where code=$1)", CODE)
        await conn.execute("delete from dataset_releases where code=$1", CODE)
        await conn.execute("delete from canonical_fields where object_id in "
                           "(select id from objects where name='ztest_unfilled_obj')")
        await conn.execute("delete from objects where name='ztest_unfilled_obj'")

    async with db.acquire() as conn:
        await purge(conn)
        oid = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_unfilled_obj') returning id", ids["org"])
        for code, name in (("dost", "Достижение, %"), ("fakt", "Факт"), ("name", "Наименование")):
            await conn.execute(
                "insert into canonical_fields(object_id,code,name,data_type,created_by) values($1,$2,$3,$4,$5)",
                oid, code, name, "text" if code == "name" else "number", ids["admin"])
        rid = await conn.fetchval(
            "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,created_by,"
            "object_id) values($1,$2,'Показатели',$3,$4,$5,$6) returning id",
            ids["org"], CODE, "validated", date(2026, 10, 6), ids["admin"], oid)
        for code in ("dost", "fakt", "name"):
            await conn.execute(
                "insert into dataset_release_fields(dataset_release_id,canonical_field_code) values($1,$2)", rid, code)
        # Строка есть, «Факт» вписан нулём, «Достижение» не заполнено вовсе.
        await conn.execute(
            "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_text) "
            "values($1,0,'Показатель 1','name','Показатель 1')", rid)
        await conn.execute(
            "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
            "values($1,0,'Показатель 1','fakt',0)", rid)
    yield
    async with db.acquire() as conn:
        await purge(conn)


async def _pv(client, headers, wt, field):
    r = await client.post("/widgets/preview", headers=headers, json={
        "widget_type": wt, "name": "T",
        "config": {"dataset_code": CODE, "value_field": field, "unit": "%" if field == "dost" else None,
                   "compare_prev": True, "spark": True,
                   "alerts": [{"level": "danger", "op": "lt", "value": 70}]}})
    assert r.status_code == 200, r.text
    return r.json()


async def test_unfilled_field_has_no_value_and_says_so(client, admin_headers, form):
    for wt in ("kpi", "gauge"):
        d = await _pv(client, admin_headers, wt, "dost")
        assert d["value"] is None, f"{wt}: незаполненная графа показана числом {d['value']}"
        assert "не заполнена" in d["no_data"] and "не ноль" in d["no_data"]
        # Порог «ниже 70 % — зона контроля» не красит отсутствие данных.
        assert d["alert"] is None


async def test_written_zero_stays_zero(client, admin_headers, form):
    for wt in ("kpi", "gauge"):
        d = await _pv(client, admin_headers, wt, "fakt")
        assert d["value"] == 0 and "no_data" not in d, d
        assert d["alert"] and d["alert"]["level"] == "danger", "вписанный ноль — сведение, порог к нему применим"
