"""Выпуск, записанный мимо штатного выпуска, объявляет свои графы.

Находка 23.09.2026: недельные выпуски 12 ведомств «Статистики услуг» писал
скрипт, и он не заполнял `dataset_release_fields`. Значения были на месте, но
мастер сборки видел у объекта НОЛЬ граф и по ведомствам не собирался вовсе.
"""
from datetime import date

import pytest
import pytest_asyncio

from app import db
from app.modules.dashboards import _suggest as sg
from app.modules.ingestion import mapping

pytestmark = pytest.mark.asyncio(loop_scope="session")

OBJ = "ztest_declare_obj"
CODE = "ztest_declare_ds"


@pytest_asyncio.fixture
async def bare_release(ids):
    """Выпуск со значениями, но без объявления граф — как у скрипта-загрузчика."""
    org = ids["org"]
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_releases where code=$1", CODE)
        await conn.execute("delete from objects where name=$1 and organization_id=$2", OBJ, org)
        obj = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,$2) returning id", org, OBJ)
        for code, name in (("ztd_prinyato", "Принято"), ("ztd_vydano", "Выдано")):
            await conn.execute(
                "insert into canonical_fields(object_id,code,name,data_type,created_by) "
                "values($1,$2,$3,'number',$4)", obj, code, name, ids["admin"])
        rel = await conn.fetchval(
            "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,"
            "created_by,object_id) values($1,$2,'тест','validated',$3,$4,$5) returning id",
            org, CODE, date(2026, 1, 8), ids["admin"], obj)
        await conn.executemany(
            "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
            "values($1,$2,$3,$4,$5)",
            [(rel, 0, "Отделение 1", "ztd_prinyato", 10), (rel, 0, "Отделение 1", "ztd_vydano", 8),
             (rel, 1, "Отделение 2", "ztd_prinyato", 5), (rel, 1, "Отделение 2", "ztd_vydano", 4)])
    yield {"object": str(obj), "release": rel}
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_releases where code=$1", CODE)
        await conn.execute("delete from objects where id=$1", obj)


async def test_bare_release_is_invisible_until_its_fields_are_declared(ids, bare_release):
    async with db.acquire() as conn:
        before = await sg.collect_object_datasets(conn, ids["org"], bare_release["object"])
        assert [len(d["fields"]) for d in before] == [0]  # сама находка: мастер не видит ни одной графы

        added = await mapping.declare_release_fields(conn, bare_release["release"])
        assert added == 2

        after = await sg.collect_object_datasets(conn, ids["org"], bare_release["object"])
        assert sorted(f["code"] for f in after[0]["fields"]) == ["ztd_prinyato", "ztd_vydano"]


async def test_declaring_twice_changes_nothing(bare_release):
    async with db.acquire() as conn:
        assert await mapping.declare_release_fields(conn, bare_release["release"]) == 2
        assert await mapping.declare_release_fields(conn, bare_release["release"]) == 0
        n = await conn.fetchval(
            "select count(*) from dataset_release_fields where dataset_release_id=$1",
            bare_release["release"])
        assert n == 2


def test_weekly_loader_declares_fields_and_numbers():
    """Скрипт-загрузчик обязан объявлять графы и заводить «Принято»/«Выдано»
    числами — иначе следующая загрузка снова сделает выпуски невидимыми."""
    from pathlib import Path
    root = Path("/deploy") if Path("/deploy/tools").exists() else Path(__file__).resolve().parents[2]
    src = (root / "tools/dnr_stats/load_weekly_file.py").read_text(encoding="utf-8")
    assert "mapping.declare_release_fields(conn, rel)" in src
    assert "'text',$4) on conflict" not in src, "все графы снова заводятся текстом"
