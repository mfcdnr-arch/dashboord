"""Расчёт данных виджета (_compute_widget) через /widgets/preview — все 12 типов.

Ловит регрессии в ядре визуализаций: каждый тип должен вернуть корректную
структуру на минимальном датасете-фикстуре `t_ds`.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _preview(client, headers, widget_type, config):
    r = await client.post("/widgets/preview", headers=headers,
                          json={"widget_type": widget_type, "name": "T", "config": config})
    assert r.status_code == 200, f"{widget_type}: {r.status_code} {r.text}"
    return r.json()


async def test_kpi(client, admin_headers, seed_dataset):
    d = await _preview(client, admin_headers, "kpi", {"dataset_code": "t_ds", "value_field": "plan"})
    assert d["type"] == "kpi"
    assert d["value"] == seed_dataset["plan_sum"]  # 180


async def test_gauge(client, admin_headers, seed_dataset):
    d = await _preview(client, admin_headers, "gauge", {"dataset_code": "t_ds", "value_field": "plan"})
    assert d["type"] == "gauge"
    assert d["value"] == seed_dataset["plan_sum"]
    assert d["max"] and d["max"] > 0


@pytest.mark.parametrize("wt", ["bar", "line", "pie"])
async def test_charts(client, admin_headers, seed_dataset, wt):
    d = await _preview(client, admin_headers, wt, {"dataset_code": "t_ds", "value_field": "plan"})
    assert d["type"] == wt
    assert d["categories"] == seed_dataset["rows"]
    assert d["values"] == seed_dataset["plan"]


async def test_table(client, admin_headers, seed_dataset):
    d = await _preview(client, admin_headers, "table", {"dataset_code": "t_ds"})
    assert d["type"] == "table"
    assert "plan" in d["columns"] and "fact" in d["columns"]
    assert len(d["rows"]) == 3


async def test_freshness_as_of(client, admin_headers, seed_dataset):
    """Свежесть: датасетный виджет несёт as_of = дата активного выпуска (2026-02-01);
    именованная метрика/текст — без as_of."""
    d = await _preview(client, admin_headers, "kpi", {"dataset_code": "t_ds", "value_field": "plan"})
    assert d.get("as_of") == "2026-02-01"
    t = await _preview(client, admin_headers, "text", {"heading": "Итоги"})
    assert t.get("as_of") is None


async def test_plan_fact(client, admin_headers, seed_dataset):
    d = await _preview(client, admin_headers, "plan_fact",
                       {"dataset_code": "t_ds", "plan_field": "plan", "fact_field": "fact"})
    assert d["type"] == "plan_fact"
    assert d["plan"] == 180 and d["fact"] == 173
    assert d["delta"] == -7


async def test_dynamics(client, admin_headers, seed_dataset):
    d = await _preview(client, admin_headers, "dynamics", {"dataset_code": "t_ds", "value_field": "plan"})
    assert d["type"] == "dynamics"
    assert len(d["periods"]) == 2  # два выпуска = два периода
    assert d["values"][-1] == 180  # активный выпуск


async def test_compare(client, admin_headers, seed_dataset):
    d = await _preview(client, admin_headers, "compare",
                       {"dataset_code": "t_ds", "value_fields": ["plan", "fact"]})
    assert d["type"] == "compare"
    assert len(d["series"]) == 2
    assert d["categories"] == seed_dataset["rows"]


async def test_heatmap(client, admin_headers, seed_dataset):
    d = await _preview(client, admin_headers, "heatmap",
                       {"dataset_code": "t_ds", "value_fields": ["plan", "fact"]})
    assert d["type"] == "heatmap"
    assert d["rows"] == seed_dataset["rows"]
    assert len(d["columns"]) == 2
    assert len(d["cells"]) == 6  # 3 строки × 2 поля
    assert d["min"] == 28 and d["max"] == 100


async def test_pivot(client, admin_headers, seed_dataset):
    d = await _preview(client, admin_headers, "pivot",
                       {"dataset_code": "t_ds", "value_fields": ["plan", "fact"]})
    assert d["type"] == "pivot"
    assert d["columns"] == ["plan", "fact"]
    assert len(d["rows"]) == 3
    assert d["rows"][0]["total"] == 190  # Паспорт: plan100+fact90
    assert d["col_totals"] == [180, 173]
    assert d["grand_total"] == 353


async def test_waterfall(client, admin_headers, seed_dataset):
    d = await _preview(client, admin_headers, "waterfall",
                       {"dataset_code": "t_ds", "value_field": "plan"})
    assert d["type"] == "waterfall"
    assert d["categories"] == seed_dataset["rows"]
    assert d["values"] == seed_dataset["plan"]  # [100,50,30]


async def test_kpi_target(client, admin_headers, seed_dataset):
    d = await _preview(client, admin_headers, "kpi",
                       {"dataset_code": "t_ds", "value_field": "plan", "target": 200})
    assert d["target"] == 200
    assert abs(d["target_pct"] - 90.0) < 0.01  # 180/200


async def test_dynamics_trend(client, admin_headers, seed_dataset):
    d = await _preview(client, admin_headers, "dynamics",
                       {"dataset_code": "t_ds", "value_field": "plan", "trend": True})
    assert len(d["trend"]) == 2
    assert d["trend_slope"] == 15  # (180 - 165) / 1 период
    assert d["trend"] == [165, 180]


async def test_objects_compare(client, admin_headers, seed_dataset):
    d = await _preview(client, admin_headers, "objects_compare", {"value_field": "plan"})
    assert d["type"] == "objects_compare"
    assert "t_obj" in d["categories"]  # тест-объект (подразделение)
    i = d["categories"].index("t_obj")
    assert d["values"][i] == 180  # сумма поля plan в последнем выпуске


async def test_objects_compare_missing_field_400(client, admin_headers):
    r = await client.post("/widgets/preview", headers=admin_headers,
                         json={"widget_type": "objects_compare", "name": "T", "config": {}})
    assert r.status_code == 400


async def test_text(client, admin_headers):
    d = await _preview(client, admin_headers, "text", {"heading": "Заголовок", "body": "Текст"})
    assert d["type"] == "text" and d["heading"] == "Заголовок"


async def test_image(client, admin_headers):
    d = await _preview(client, admin_headers, "image", {"url": "data:image/png;base64,AAAA"})
    assert d["type"] == "image" and d["url"].startswith("data:")


async def test_unknown_type_400(client, admin_headers):
    r = await client.post("/widgets/preview", headers=admin_headers,
                         json={"widget_type": "bogus", "name": "T", "config": {}})
    assert r.status_code == 400


async def test_kpi_missing_source_400(client, admin_headers):
    r = await client.post("/widgets/preview", headers=admin_headers,
                         json={"widget_type": "kpi", "name": "T", "config": {}})
    assert r.status_code == 400
