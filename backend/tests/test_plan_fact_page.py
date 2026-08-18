"""Сводная страница «План/факт» по ВСЕМ папкам (запрос заказчика 17.08).

Отличие от полосы «план-факт» в дашборде объекта: та про одну форму из одной
папки и остаётся как была. Здесь — общая картина по организации.

Шкала: <50 % красный, 50–70 оранжевый, 70–85 жёлтый, от 85 % зелёный.
Перевыполнение остаётся зелёным (решение заказчика): это не проблема, а точное
значение подписано числом рядом с полосой.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.dashboards._alerts import evaluate_alert
from app.modules.dashboards._planfact import PLAN_FACT_SCALE


def test_scale_colours_every_band():
    """Каждая ступень шкалы даёт свой цвет, границы принадлежат верхней ступени."""
    cfg = {"alerts": [dict(r) for r in PLAN_FACT_SCALE], "alert_on": "pct"}

    def level(pct):
        return (evaluate_alert("plan_fact", cfg, {"pct": pct}) or {}).get("level")

    assert level(0) == "danger"
    assert level(49.9) == "danger"
    assert level(50) == "poor", "50 % — уже оранжевый, а не красный"
    assert level(69.9) == "poor"
    assert level(70) == "warn", "70 % — уже жёлтый"
    assert level(84.9) == "warn"
    assert level(85) == "good", "85 % — уже зелёный"
    assert level(100) == "good"
    # Перевыполнение остаётся зелёным: отдельного цвета для него не заводим.
    assert level(656.87) == "good"


def test_scale_order_is_significant():
    """Правила проверяются сверху вниз — порядок менять нельзя.

    Если «good ≥85» встанет первым, он перехватит и 40 %, и 90 %: сработает
    первое подходящее правило, а `gte 85` для 40 % не подходит — но `lt 70`
    для 40 % подходит тоже, и порядок решает, какой цвет увидит человек.
    """
    assert [r["level"] for r in PLAN_FACT_SCALE] == ["danger", "poor", "warn", "good"]
    assert [r["value"] for r in PLAN_FACT_SCALE] == [50, 70, 85, 85]


async def test_collects_pairs_from_all_objects_and_rebuilds(client, admin_headers, seed_dataset):
    """Пары ищутся по всем объектам; пересборка меняет наполнение, не дашборд."""
    from app.modules.dashboards import _planfact

    async with db.acquire() as conn:
        org = await conn.fetchval(
            "select organization_id from dataset_releases where code=$1 limit 1", seed_dataset["code"])
        obj = await conn.fetchval(
            "select object_id from dataset_releases where code=$1 limit 1", seed_dataset["code"])
        # Фикстура заводит значения в обход конвейера и НЕ создаёт справочник
        # полей, а пары «План + Факт» строятся именно по названиям граф.
        for code, name in (
            ("plan", "Заявок принято · План (до 1 сентября 2026 г.)*"),
            ("fact", "Заявок принято · Факт · нарастающим итогом**"),
        ):
            await conn.execute(
                "insert into canonical_fields(object_id, code, name) values($1,$2,$3) "
                "on conflict (object_id, code) do update set name=excluded.name", obj, code, name)
            await conn.execute(
                "update canonical_fields set data_type='number' where object_id=$1 and code=$2", obj, code)
        # Фикстура не создаёт и dataset_release_fields — а список показателей
        # набора строится именно по ним (что реально выпущено), не по справочнику.
        for rel in await conn.fetch(
                "select id from dataset_releases where code=$1", seed_dataset["code"]):
            for code in ("plan", "fact"):
                await conn.execute(
                    "insert into dataset_release_fields(dataset_release_id, canonical_field_code) "
                    "values($1,$2) on conflict do nothing", rel["id"], code)
    did = None
    try:
        async with db.acquire() as conn:
            found = await _planfact.collect_plan_fact(conn, org)
        # На стенде есть и НАСТОЯЩИЕ объекты заказчика, поэтому ищем именно
        # свою пару, а не первую попавшуюся: порядок обхода объектов не наш.
        mine = [f for f in found if f["dataset_code"] == seed_dataset["code"]]
        assert mine, "пара «План + Факт» должна найтись по названиям граф"
        assert mine[0]["plan"]["code"] == "plan" and mine[0]["fact"]["code"] == "fact"

        r = await client.post("/dashboards/plan-fact", headers=admin_headers, json={"name": "ztest_pf"})
        assert r.status_code == 201, r.text
        out = r.json()
        did = out["dashboard_id"]
        assert out["widgets"] >= 1

        # Виджет получил именно нашу шкалу, а не общую норму 90/100.
        async with db.acquire() as conn:
            cfg = await conn.fetchval(
                "select config from widgets where dashboard_id=$1::uuid limit 1", did)
        import json as _json
        cfg = _json.loads(cfg) if isinstance(cfg, str) else cfg
        assert [x["value"] for x in cfg["alerts"]] == [50, 70, 85, 85]
        assert cfg["alert_on"] == "pct"

        # Пересборка: наполнение заменяется, сам дашборд остаётся тем же.
        r2 = await client.post("/dashboards/plan-fact", headers=admin_headers,
                               json={"dashboard_id": did})
        assert r2.status_code == 201, r2.text
        assert r2.json()["dashboard_id"] == did, "пересборка не должна плодить дашборды"
        async with db.acquire() as conn:
            pages = await conn.fetchval(
                "select count(*) from dashboard_pages where dashboard_id=$1::uuid", did)
        assert pages == 1, "страница одна, а не добавляется каждый раз"
    finally:
        async with db.acquire() as conn:
            if did:
                await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
                await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
                await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
                await conn.execute("delete from audit_log where entity_id=$1::uuid", did)
                await conn.execute("delete from dashboards where id=$1::uuid", did)
            await conn.execute(
                "delete from dataset_release_fields where dataset_release_id in "
                "(select id from dataset_releases where code=$1)", seed_dataset["code"])
            await conn.execute(
                "delete from canonical_fields where object_id=$1 and code=any($2::text[])",
                obj, ["plan", "fact"])


async def test_no_pairs_gives_honest_refusal(client, admin_headers):
    """Пустой дашборд не собираем: человек решит, что система сломалась."""
    r = await client.post("/dashboards/plan-fact", headers=admin_headers, json={})
    # На стенде без граф с ролью «План» — отказ с настоящей причиной.
    if r.status_code == 400:
        assert "План" in r.json()["detail"]
    else:
        # Пары нашлись (данные стенда) — тогда просто убираем за собой.
        did = r.json()["dashboard_id"]
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from audit_log where entity_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)
