"""Перепривязка датасетов/метрик при клонировании шаблона дашборда."""
import pytest

from conftest import purge_dashboard  # noqa: E402
from app import db  # noqa: E402
from app.modules.dashboards import service as svc  # noqa: E402


def test_template_codes_extraction():
    spec = {"pages": [{"widgets": [
        {"config": {"dataset_code": "ds1", "value_field": "x"}},
        {"config": {"metric_code": "m1"}},
        {"config": {"plan_metric": "m2", "fact_metric": "m3"}},
        {"config": {}},
    ]}]}
    codes = svc._template_codes(spec)
    assert codes["datasets"] == ["ds1"]
    assert codes["metrics"] == ["m1", "m2", "m3"]


def test_remap_config():
    cfg = {"dataset_code": "old_ds", "value_field": "x", "metric_code": "old_m"}
    out = svc._remap_config(cfg, {"old_ds": "new_ds"}, {"old_m": "new_m"})
    assert out["dataset_code"] == "new_ds"
    assert out["metric_code"] == "new_m"
    assert out["value_field"] == "x"  # прочее не трогаем
    # без карт — как есть
    assert svc._remap_config(cfg, {}, {})["dataset_code"] == "old_ds"


@pytest.mark.asyncio(loop_scope="session")
async def test_template_bindings_and_instantiate(client, admin_headers, seed_dataset):
    # дашборд → страница → виджет на t_ds → сохранить как шаблон
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_tpl_src"})).json()["id"]
    tid = None
    made = None
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "P"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "k", "widget_type": "kpi", "config": {"dataset_code": "t_ds", "value_field": "plan"}})
        r = await client.post(f"/dashboards/{did}/save-template", headers=admin_headers, json={"name": "ztest_tpl"})
        assert r.status_code in (200, 201), r.text
        tid = r.json()["id"]
        # bindings показывают используемый код датасета
        b = (await client.get(f"/dashboard-templates/{tid}/bindings", headers=admin_headers)).json()
        assert "t_ds" in b["datasets"]
        # инстанцируем с картой (t_ds → t_ds; проверяем, что путь с картой работает)
        r = await client.post(f"/dashboard-templates/{tid}/instantiate", headers=admin_headers,
                              json={"name": "ztest_tpl_new", "dataset_map": {"t_ds": "t_ds"}})
        assert r.status_code == 201, r.text
        made = r.json()["dashboard_id"]
    finally:
        if made:
            await purge_dashboard(made)
        if tid:
            async with db.acquire() as conn:
                await conn.execute("delete from dashboard_templates where id=$1::uuid", tid)
        await purge_dashboard(did)
