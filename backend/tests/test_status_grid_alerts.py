"""Светофор без порогов выглядел сломанным ровно в том, ради чего его берут.

Плитки красятся по порогам из `config.alerts`. Пороги задаются кнопкой ⚠, и
пока человек её не открыл, ВСЕ плитки одного цвета — то есть «светофор» не
светит. При этом выдумывать норму нельзя: у «доли доставленных» её нет.

Разрешение то же, что принято 16.08 для полосы «план-факт» и спидометра: если
у светофора задано поле ПЛАНА, норма известна — 100 % это сам план, и пороги
90/100 % ставятся сразу. Без плана — не ставятся.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db


async def _dash(client, headers, name):
    did = (await client.post("/dashboards", headers=headers, json={"name": name})).json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=headers, json={"name": "Обзор"})).json()["id"]
    return did, pid


async def _drop(did):
    async with db.acquire() as conn:
        await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
        await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
        await conn.execute("delete from audit_log where entity_id=$1::uuid", did)
        await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_status_grid_with_plan_gets_norm_without_plan_does_not(client, admin_headers, seed_dataset):
    did, pid = await _dash(client, admin_headers, "ztest_sg_norm")
    try:
        ds = seed_dataset["code"]
        # С планом: норма известна (100 % — сам план), плитки должны краситься.
        w1 = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "ztest Светофор с планом", "widget_type": "status_grid",
            "config": {"dataset_code": ds, "value_field": "fact", "plan_field": "plan"}})).json()["id"]
        data = (await client.get(f"/widgets/{w1}/data", headers=admin_headers)).json()
        assert data["compared_to_plan"] is True
        assert all(c["pct"] is not None for c in data["cells"])
        # Каждая плитка получила цвет — именно этого и ждут от светофора.
        assert all(c["level"] for c in data["cells"]), data["cells"]
        # И цвет отвечает норме, а не просто «какой-нибудь»: план 100/50/30,
        # факт 90/55/28 → 90 % (не выполнен), 110 % (выполнен), 93 % (не выполнен).
        by_row = {c["label"]: c["level"] for c in data["cells"]}
        assert by_row["Паспорт"] == "warn"
        assert by_row["ИНН"] == "good"
        assert by_row["СНИЛС"] == "warn"

        # Без плана нормы нет — выдуманное правило хуже отсутствующего.
        w2 = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "ztest Светофор без плана", "widget_type": "status_grid",
            "config": {"dataset_code": ds, "value_field": "fact"}})).json()["id"]
        data2 = (await client.get(f"/widgets/{w2}/data", headers=admin_headers)).json()
        assert data2["compared_to_plan"] is False
        assert all(c["level"] is None for c in data2["cells"])
    finally:
        await _drop(did)


async def test_explicitly_cleared_thresholds_are_not_restored(client, admin_headers, seed_dataset):
    """Пустой список порогов — это осознанно снятые правила, а не «не задано»:
    возвращать их значило бы спорить с человеком при каждом сохранении."""
    did, pid = await _dash(client, admin_headers, "ztest_sg_cleared")
    try:
        wid = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "ztest Светофор", "widget_type": "status_grid",
            "config": {"dataset_code": seed_dataset["code"], "value_field": "fact", "plan_field": "plan"}})).json()["id"]

        r = await client.patch(f"/widgets/{wid}", headers=admin_headers, json={
            "config": {"dataset_code": seed_dataset["code"], "value_field": "fact",
                       "plan_field": "plan", "alerts": []}})
        assert r.status_code == 200, r.text
        data = (await client.get(f"/widgets/{wid}/data", headers=admin_headers)).json()
        assert all(c["level"] is None for c in data["cells"])

        # Свои пороги тоже не перетираются умолчанием.
        await client.patch(f"/widgets/{wid}", headers=admin_headers, json={
            "config": {"dataset_code": seed_dataset["code"], "value_field": "fact", "plan_field": "plan",
                       "alerts": [{"level": "danger", "op": "lt", "value": 50}]}})
        async with db.acquire() as conn:
            cfg = await conn.fetchval("select config from widgets where id=$1::uuid", wid)
        import json
        rules = (json.loads(cfg) if isinstance(cfg, str) else cfg)["alerts"]
        assert len(rules) == 1 and rules[0]["value"] == 50
    finally:
        await _drop(did)
