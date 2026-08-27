"""Раздел «Статистика услуг ДНР»: сводный «Обзор» + multi-release история.

Своя фикстура `dnr_object` заводит ОТДЕЛЬНЫЙ тестовый объект с двумя релизами
кода `mvd_offices` (тот же код, что у реального ведомства МВД в каталоге
`DEPARTMENTS`, — раздел ищет данные ПО КОДУ независимо от объекта, поэтому
тестовые данные не пересекаются с рабочими данными заказчика на дев-стенде).
Дев-БД общая (не отдельная тестовая схема), поэтому проверки построены на
ПРИСУТСТВИИ ожидаемых записей (алерт по нашему офису, наша точка тренда), а
не на точном совпадении всего ответа — в организации может быть и реальный
паспорт КПЭ, который добавит свои алерты, и это нормально.
"""
from datetime import date

import pytest
import pytest_asyncio

from app import db

from conftest import hdr, login

pytestmark = pytest.mark.asyncio(loop_scope="session")

OBJECT_NAME = "ztest_dnr_obj"
DEPT_CODE = "mvd"
DATASET_CODE = "mvd_offices"


# Каталог МВД в departments.py несёт 8 услуг; чтобы неупомянутые в тесте
# услуги не попали в алерт «не оказывается» (там нет данных вообще — окажется
# «нет» из-за отсутствия значения), по умолчанию они считаются оказываемыми
# и нулевыми — в тесте явно задаются только те, что нужны сценарию (s1/s2).
ALL_SERVICE_KEYS = [f"s{i}" for i in range(1, 9)]


async def _seed_release(conn, org_id, object_id, period, admin_id, offices):
    """offices: {office_label: {"s1": (prinyato, vydano, okazyvaetsya), ...}}"""
    rel = await conn.fetchval(
        "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,created_by,object_id) "
        "values($1,$2,'Тест МВД','validated',$3,$4,$5) returning id",
        org_id, DATASET_CODE, date.fromisoformat(period), admin_id, object_id)
    numbers, texts = [], [(rel, i, office, "gorod", "Тестгород") for i, office in enumerate(offices)]
    for i, (office, svcs_in) in enumerate(offices.items()):
        svcs = {k: svcs_in.get(k, (0, 0, "да")) for k in ALL_SERVICE_KEYS}
        for skey, (prinyato, vydano, okazyvaetsya) in svcs.items():
            numbers.append((rel, i, office, f"mvd_{skey}_prinyato", prinyato))
            numbers.append((rel, i, office, f"mvd_{skey}_vydano", vydano))
            texts.append((rel, i, office, f"mvd_{skey}_okazyvaetsya", okazyvaetsya))
    await conn.executemany(
        "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
        "values($1,$2,$3,$4,$5)", numbers)
    await conn.executemany(
        "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_text) "
        "values($1,$2,$3,$4,$5)", texts)
    return rel


@pytest_asyncio.fixture
async def dnr_object(ids):
    org_id, admin_id = ids["org"], ids["admin"]
    async with db.acquire() as conn:
        await conn.execute(
            "delete from dataset_values where dataset_release_id in "
            "(select id from dataset_releases where code=$1 and object_id in "
            "(select id from objects where name=$2 and organization_id=$3))",
            DATASET_CODE, OBJECT_NAME, org_id)
        await conn.execute(
            "delete from dataset_releases where code=$1 and object_id in "
            "(select id from objects where name=$2 and organization_id=$3)",
            DATASET_CODE, OBJECT_NAME, org_id)
        await conn.execute("delete from objects where name=$1 and organization_id=$2", OBJECT_NAME, org_id)
        object_id = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,$2) returning id", org_id, OBJECT_NAME)

        # Точка 1: "Растущее" отделение (+20) и "застойное" (без изменений).
        await _seed_release(conn, org_id, object_id, "2026-01-01", admin_id, {
            "Растущее": {"s1": (100, 90, "да")},
            "Застойное": {"s1": (50, 45, "да")},
        })
        # Точка 2 (последняя): растущее выросло, застойное — нулевой прирост.
        # Услуга 2 нигде не оказывается («нет» на обоих офисах) — проверка
        # алерта "не оказывается услуг".
        rel2 = await _seed_release(conn, org_id, object_id, "2026-01-08", admin_id, {
            "Растущее": {"s1": (120, 100, "да"), "s2": (0, 0, "нет")},
            "Застойное": {"s1": (50, 45, "да"), "s2": (0, 0, "нет")},
        })
    yield {"object_id": str(object_id), "rel2": str(rel2)}
    async with db.acquire() as conn:
        await conn.execute(
            "delete from dataset_values where dataset_release_id in "
            "(select id from dataset_releases where code=$1 and object_id=$2::uuid)", DATASET_CODE, object_id)
        await conn.execute("delete from dataset_releases where code=$1 and object_id=$2::uuid", DATASET_CODE, object_id)
        await conn.execute("delete from objects where id=$1::uuid", object_id)


async def test_overview_trend_and_growth(client, admin_headers, dnr_object):
    r = await client.get(f"/dnr-stats/{dnr_object['object_id']}/overview", headers=admin_headers)
    assert r.status_code == 200, r.text
    d = r.json()

    periods = [p["period"] for p in d["trend"]]
    assert "2026-01-01" in periods and "2026-01-08" in periods
    p1 = next(p for p in d["trend"] if p["period"] == "2026-01-01")
    p2 = next(p for p in d["trend"] if p["period"] == "2026-01-08")
    assert p1["prinyato"] == 150.0  # 100 + 50
    assert p2["prinyato"] == 170.0  # 120 + 50 (услуга 2 — нули с обеих сторон)

    mvd = next(x for x in d["departments"] if x["code"] == "mvd")
    assert mvd["prinyato"] == 170.0
    assert mvd["growth"] == 20.0  # 170 - 150

    assert d["offices_total"] == 2
    # «Растущее» выросло, «Застойное» — нулевой прирост → должно попасть в алерт.
    assert any("Застойное" in a["text"] for a in d["alerts"] if a["kind"] == "zero_growth")
    assert not any("Растущее" in a["text"] for a in d["alerts"] if a["kind"] == "zero_growth")


async def test_overview_service_gap_alert(client, admin_headers, dnr_object):
    r = await client.get(f"/dnr-stats/{dnr_object['object_id']}/overview", headers=admin_headers)
    d = r.json()
    gap = next((a for a in d["alerts"] if a["kind"] == "service_gap"), None)
    assert gap is not None
    assert "1 из 8" in gap["text"]  # ровно одна услуга (s2) не оказывается нигде
    assert d["services_active"] == 7
    assert d["services_total"] == 8


async def test_overview_uses_last_two_releases_only(client, admin_headers, dnr_object, ids):
    """Третья, более новая точка обязана СМЕНИТЬ пару «было/стало», а не
    добавиться сбоку — иначе «Обзор» и список отделений начали бы противоречить
    друг другу при накоплении истории."""
    async with db.acquire() as conn:
        rel3 = await _seed_release(conn, ids["org"], dnr_object["object_id"], "2026-01-15", ids["admin"], {
            "Растущее": {"s1": (200, 150, "да"), "s2": (0, 0, "нет")},
            "Застойное": {"s1": (50, 45, "да"), "s2": (0, 0, "нет")},
        })
    try:
        r = await client.get(f"/dnr-stats/{dnr_object['object_id']}/overview", headers=admin_headers)
        d = r.json()
        assert d["as_of"] == "2026-01-15"
        assert d["period_prev"] == "2026-01-08"
        mvd = next(x for x in d["departments"] if x["code"] == "mvd")
        assert mvd["prinyato"] == 250.0  # 200 + 50, точка "2026-01-01" больше не участвует в сравнении
        assert mvd["growth"] == 80.0  # 250 - 170

        r2 = await client.get(
            f"/dnr-stats/{dnr_object['object_id']}/office-department"
            f"?office=Растущее&dept=mvd", headers=admin_headers)
        dep = r2.json()
        assert dep["period_prev"] == "2026-01-08" and dep["period_now"] == "2026-01-15"
        assert dep["prinyato_prev"] == 120.0 and dep["prinyato_now"] == 200.0
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from dataset_values where dataset_release_id=$1::uuid", rel3)
            await conn.execute("delete from dataset_releases where id=$1::uuid", rel3)


async def test_view_access_gating(client, admin_headers, moderator_user, viewer, dnr_object):
    # staff (admin/модератор) — доступ есть всегда.
    r = await client.get(f"/dnr-stats/{dnr_object['object_id']}/overview", headers=admin_headers)
    assert r.status_code == 200
    r = await client.get(f"/dnr-stats/{dnr_object['object_id']}/overview", headers=moderator_user["headers"])
    assert r.status_code == 200

    # Обычный пользователь без «Руководителю» — заблокирован.
    r = await client.get(f"/dnr-stats/{dnr_object['object_id']}/overview", headers=viewer["headers"])
    assert r.status_code == 403

    # Та же учётка после включения show_featured — пропущена.
    async with db.acquire() as conn:
        await conn.execute("update users set show_featured=true where id=$1::uuid", viewer["id"])
    token = await login(client, "ztest_viewer", "viewer123")
    r = await client.get(f"/dnr-stats/{dnr_object['object_id']}/overview", headers=hdr(token))
    assert r.status_code == 200
    r = await client.get(f"/dnr-stats/{dnr_object['object_id']}/offices", headers=hdr(token))
    assert r.status_code == 200
