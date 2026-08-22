"""Drill-down по строке: место строки среди остальных.

Клик по строке таблицы проваливает страницу в эту строку. Сама по себе её
цифра не отвечает на вопрос, ради которого туда и проваливаются, — «это много
или мало на фоне других». Здесь проверяется расчёт ответа.
"""
import pytest

from conftest import purge_dashboard

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_rank_uses_page_dataset_and_orders_rows(client, admin_headers, seed_dataset):
    """Место, доля и лидер считаются по датасету и полям САМОЙ страницы."""
    d = (await client.post("/dashboards", json={"name": "ztest_rank_dash"}, headers=admin_headers)).json()
    p = (await client.post(f"/dashboards/{d['id']}/pages", json={"name": "Обзор"}, headers=admin_headers)).json()
    # Два виджета на одном датасете: fact встречается чаще → он и главный.
    for wt, cfg in (
        ("table", {"dataset_code": "t_ds", "value_fields": ["plan", "fact"]}),
        ("kpi", {"dataset_code": "t_ds", "value_field": "fact"}),
    ):
        r = await client.post(f"/dashboard-pages/{p['id']}/widgets",
                              json={"name": f"w-{wt}", "widget_type": wt, "config": cfg},
                              headers=admin_headers)
        assert r.status_code == 201, r.text

    rows = (await client.get(f"/dashboard-pages/{p['id']}/data", headers=admin_headers)).json()["widgets"]
    table = next(w["data"] for w in rows if w.get("data", {}).get("type") == "table")
    labels = [r["row"] for r in table["rows"]]
    assert len(labels) > 1, "фикстура должна давать несколько строк, иначе ранжировать нечего"

    # Берём строку с самым большим fact — она обязана оказаться первой.
    top = max(table["rows"], key=lambda r: r["fact"])["row"]
    res = (await client.get(f"/dashboard-pages/{p['id']}/row-rank",
                            params={"row": top}, headers=admin_headers)).json()
    assert res["dataset_code"] == "t_ds"
    assert res["rows_total"] == len(labels)
    m = {x["field"]: x for x in res["metrics"]}
    assert "fact" in m, "поле страницы не попало в разбор"
    assert m["fact"]["rank"] == 1
    assert m["fact"]["leader"] == top
    # Доля от итога — не проценты «от балды»: сумма долей всех строк равна 100.
    total = sum(r["fact"] for r in table["rows"])
    assert abs(m["fact"]["share"] - m["fact"]["value"] / total * 100) < 0.01

    # Последняя строка по fact — последнее место, и лидер у неё чужой.
    low = min(table["rows"], key=lambda r: r["fact"])["row"]
    res2 = (await client.get(f"/dashboard-pages/{p['id']}/row-rank",
                             params={"row": low}, headers=admin_headers)).json()
    m2 = {x["field"]: x for x in res2["metrics"]}
    assert m2["fact"]["rank"] == len(labels)
    assert m2["fact"]["leader"] == top

    await purge_dashboard(d["id"])


async def test_rank_is_honest_when_there_is_nothing_to_compare(client, admin_headers, seed_dataset):
    """Страница без датасетных виджетов — пустой разбор, а не ошибка."""
    d = (await client.post("/dashboards", json={"name": "ztest_rank_empty"}, headers=admin_headers)).json()
    p = (await client.post(f"/dashboards/{d['id']}/pages", json={"name": "Текст"}, headers=admin_headers)).json()
    await client.post(f"/dashboard-pages/{p['id']}/widgets",
                      json={"name": "заголовок", "widget_type": "text", "config": {"heading": "Привет"}},
                      headers=admin_headers)
    res = (await client.get(f"/dashboard-pages/{p['id']}/row-rank",
                            params={"row": "Донецк"}, headers=admin_headers)).json()
    assert res["metrics"] == [] and res["dataset_code"] is None

    # Несуществующая строка: разбор пуст, но запрос не падает.
    p2 = (await client.post(f"/dashboards/{d['id']}/pages", json={"name": "Данные"}, headers=admin_headers)).json()
    await client.post(f"/dashboard-pages/{p2['id']}/widgets",
                      json={"name": "kpi", "widget_type": "kpi", "config": {"dataset_code": "t_ds", "value_field": "fact"}},
                      headers=admin_headers)
    res2 = (await client.get(f"/dashboard-pages/{p2['id']}/row-rank",
                             params={"row": "Такой строки нет"}, headers=admin_headers)).json()
    assert res2["metrics"] == []
    # Пустая строка — отказ, а не молчаливый пустой ответ.
    bad = await client.get(f"/dashboard-pages/{p2['id']}/row-rank", params={"row": " "}, headers=admin_headers)
    assert bad.status_code == 400

    await purge_dashboard(d["id"])


async def test_rank_hidden_for_foreign_page(client, admin_headers, viewer, seed_dataset):
    """Чужая страница не отдаёт разбор — тем же правилом, что и её виджеты."""
    d = (await client.post("/dashboards", json={"name": "ztest_rank_secret"}, headers=admin_headers)).json()
    p = (await client.post(f"/dashboards/{d['id']}/pages", json={"name": "Обзор"}, headers=admin_headers)).json()
    r = await client.get(f"/dashboard-pages/{p['id']}/row-rank", params={"row": "Донецк"}, headers=viewer["headers"])
    assert r.status_code == 404
    await purge_dashboard(d["id"])
