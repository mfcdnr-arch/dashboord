"""Раздел «Статистика услуг ДНР»: сводный «Обзор» + multi-release история.

Раздел ORG-WIDE (без привязки к object_id — у каждого ведомства свой объект),
поэтому изоляция теста ДОЛЖНА идти через собственный код ведомства и
подменённый `DEPARTMENTS` (`monkeypatch`), а не через отдельный object_id —
иначе тестовые данные под кодом РЕАЛЬНОГО ведомства (например, `mvd_offices`)
сольются с рабочими данными заказчика на дев-стенде, потому что раздел ищет
данные по коду датасета во всей организации. `DEPARTMENTS` подменяется на
словарь из ОДНОГО тестового ведомства — иначе `overview()` заодно просуммировал
бы реальные 12 ведомств заказчика, и итоги (`services_total` и т.п.) перестали
бы совпадать с ожидаемыми в тесте числами.
"""
from datetime import date

import pytest
import pytest_asyncio

from app import db
from app.modules.dnr_stats import service
from app.modules.dnr_stats.departments import field

from conftest import hdr, login

pytestmark = pytest.mark.asyncio(loop_scope="session")

OBJECT_NAME = "ztest_dnr_obj"
DEPT_CODE = "ztest"
DATASET_CODE = "ztest_dept_offices"
N_SERVICES = 2
TEST_DEPARTMENTS = {
    DEPT_CODE: {"name": "Тестовое ведомство", "dataset_code": DATASET_CODE,
                "services": ["Тестовая услуга 1", "Тестовая услуга 2"]},
}

ALL_SERVICE_KEYS = [f"s{i}" for i in range(1, N_SERVICES + 1)]


@pytest.fixture(autouse=True)
def _isolated_departments(monkeypatch):
    """Раздел видит ТОЛЬКО тестовое ведомство — реальные 12 ведомств заказчика
    не примешиваются к суммам и алертам, которые тест проверяет поимённо."""
    monkeypatch.setattr(service, "DEPARTMENTS", TEST_DEPARTMENTS)


async def _seed_release(conn, org_id, object_id, period, admin_id, offices):
    """offices: {office_label: {"s1": (prinyato, vydano, okazyvaetsya), ...}}"""
    rel = await conn.fetchval(
        "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,created_by,object_id) "
        "values($1,$2,'Тест ведомства','validated',$3,$4,$5) returning id",
        org_id, DATASET_CODE, date.fromisoformat(period), admin_id, object_id)
    numbers, texts = [], [(rel, i, office, "gorod", "Тестгород") for i, office in enumerate(offices)]
    for i, (office, svcs_in) in enumerate(offices.items()):
        svcs = {k: svcs_in.get(k, (0, 0, "да")) for k in ALL_SERVICE_KEYS}
        for skey, (prinyato, vydano, okazyvaetsya) in svcs.items():
            svc_i = int(skey[1:])
            numbers.append((rel, i, office, field(DEPT_CODE, svc_i, "prinyato"), prinyato))
            numbers.append((rel, i, office, field(DEPT_CODE, svc_i, "vydano"), vydano))
            texts.append((rel, i, office, field(DEPT_CODE, svc_i, "okazyvaetsya"), okazyvaetsya))
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
            "(select id from dataset_releases where code=$1)", DATASET_CODE)
        await conn.execute("delete from dataset_releases where code=$1", DATASET_CODE)
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
            "(select id from dataset_releases where code=$1)", DATASET_CODE)
        await conn.execute("delete from dataset_releases where code=$1", DATASET_CODE)
        await conn.execute("delete from objects where id=$1::uuid", object_id)


async def test_overview_trend_and_growth(client, admin_headers, dnr_object):
    r = await client.get("/dnr-stats/overview", headers=admin_headers)
    assert r.status_code == 200, r.text
    d = r.json()

    periods = [p["period"] for p in d["trend"]]
    assert periods == ["2026-01-01", "2026-01-08"]
    p1 = next(p for p in d["trend"] if p["period"] == "2026-01-01")
    p2 = next(p for p in d["trend"] if p["period"] == "2026-01-08")
    assert p1["prinyato"] == 150.0  # 100 + 50
    assert p2["prinyato"] == 170.0  # 120 + 50 (услуга 2 — нули с обеих сторон)

    dept = next(x for x in d["departments"] if x["code"] == DEPT_CODE)
    assert dept["prinyato"] == 170.0
    assert dept["growth"] == 20.0  # 170 - 150

    assert d["offices_total"] == 2
    # «Растущее» выросло, «Застойное» — нулевой прирост → должно попасть в алерт.
    assert any("Застойное" in a["text"] for a in d["alerts"] if a["kind"] == "zero_growth")
    assert not any("Растущее" in a["text"] for a in d["alerts"] if a["kind"] == "zero_growth")


async def test_overview_service_gap_alert(client, admin_headers, dnr_object):
    r = await client.get("/dnr-stats/overview", headers=admin_headers)
    d = r.json()
    gap = next((a for a in d["alerts"] if a["kind"] == "service_gap"), None)
    assert gap is not None
    assert f"1 из {N_SERVICES}" in gap["text"]  # ровно одна услуга (s2) не оказывается нигде
    assert d["services_active"] == N_SERVICES - 1
    assert d["services_total"] == N_SERVICES


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
        r = await client.get("/dnr-stats/overview", headers=admin_headers)
        d = r.json()
        assert d["as_of"] == "2026-01-15"
        assert d["period_prev"] == "2026-01-08"
        dept = next(x for x in d["departments"] if x["code"] == DEPT_CODE)
        assert dept["prinyato"] == 250.0  # 200 + 50, точка "2026-01-01" больше не участвует в сравнении
        assert dept["growth"] == 80.0  # 250 - 170

        r2 = await client.get(
            "/dnr-stats/office-department?office=Растущее&dept=" + DEPT_CODE, headers=admin_headers)
        dep = r2.json()
        assert dep["period_prev"] == "2026-01-08" and dep["period_now"] == "2026-01-15"
        assert dep["prinyato_prev"] == 120.0 and dep["prinyato_now"] == 200.0
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from dataset_values where dataset_release_id=$1::uuid", rel3)
            await conn.execute("delete from dataset_releases where id=$1::uuid", rel3)


async def test_view_access_gating(client, admin_headers, moderator_user, viewer, dnr_object):
    # staff (admin/модератор) — доступ есть всегда.
    r = await client.get("/dnr-stats/overview", headers=admin_headers)
    assert r.status_code == 200
    r = await client.get("/dnr-stats/overview", headers=moderator_user["headers"])
    assert r.status_code == 200

    # Обычный пользователь без «Руководителю» — заблокирован.
    r = await client.get("/dnr-stats/overview", headers=viewer["headers"])
    assert r.status_code == 403

    # Та же учётка после включения show_featured — пропущена.
    async with db.acquire() as conn:
        await conn.execute("update users set show_featured=true where id=$1::uuid", viewer["id"])
    token = await login(client, "ztest_viewer", "viewer123")
    r = await client.get("/dnr-stats/overview", headers=hdr(token))
    assert r.status_code == 200
    r = await client.get("/dnr-stats/offices", headers=hdr(token))
    assert r.status_code == 200


async def test_overview_names_the_services_offered_nowhere(client, admin_headers, dnr_object):
    """Услуги, которых нет НИГДЕ, — списком, а не одной строкой алерта.

    «Не оказывается 5 из 67» не говорит, каких именно, и разобраться по такой
    строке нельзя. Ведомство названо рядом: услуги у ведомств одноимённые.
    """
    d = (await client.get("/dnr-stats/overview", headers=admin_headers)).json()
    missing = d["services_missing"]
    assert [x["service"] for x in missing] == ["Тестовая услуга 2"]
    assert missing[0]["dept"] == "Тестовое ведомство"


async def test_overview_compares_departments_side_by_side(client, admin_headers, dnr_object):
    """Сравнение ведомств между собой: доля в объёме, конверсия, охват."""
    d = (await client.get("/dnr-stats/overview", headers=admin_headers)).json()
    dept = next(x for x in d["departments"] if x["code"] == DEPT_CODE)
    # Ведомство одно — вся доля его; конверсия = выдано / принято.
    assert round(dept["share_pct"], 1) == 100.0
    assert round(dept["conversion_pct"], 1) == round(145 / 170 * 100, 1)
    assert dept["offices"] == 2
    assert dept["services_active"] == 1 and dept["services_total"] == N_SERVICES


async def test_office_gap_separates_refusal_from_an_empty_cell(client, admin_headers, dnr_object, ids):
    """🔴 «Нет» и ПУСТО — разные вещи, и складывать их в один счётчик нельзя.

    «Нет» — услугу здесь осознанно не оказывают; пустая клетка — про услугу
    ничего не известно. Сложи их вместе, и пробел в отчёте выдаётся за факт об
    отделении. Проверяем на отделении, где у соседа услуга ЕСТЬ.
    """
    async with db.acquire() as conn:
        object_id = await conn.fetchval("select id from objects where name=$1 and organization_id=$2",
                                        OBJECT_NAME, ids["org"])
        # Третья точка: у «Растущего» услуга 2 появилась, у «Застойного» стоит
        # «нет», а у третьего отделения графа пуста вовсе.
        await _seed_release(conn, ids["org"], object_id, "2026-01-15", ids["admin"], {
            "Растущее": {"s1": (130, 110, "да"), "s2": (5, 4, "01.01.2026")},
            "Застойное": {"s1": (50, 45, "да"), "s2": (0, 0, "нет")},
            "Молчащее": {"s1": (10, 9, "да"), "s2": (0, 0, "")},
        })
    d = (await client.get("/dnr-stats/overview", headers=admin_headers)).json()
    gaps = {g["office"]: g for g in d["office_gaps"]}
    assert gaps["Застойное"]["refused"] == 1 and gaps["Застойное"]["unknown"] == 0
    assert gaps["Молчащее"]["unknown"] == 1 and gaps["Молчащее"]["refused"] == 0
    # У кого услуга есть — в списке пробелов его быть не должно.
    assert "Растущее" not in gaps
    # И услуга больше не числится «не оказываемой нигде».
    assert d["services_missing"] == []
