"""Два новых виджета: воронка и «светофор» по строкам.

**Воронка** отвечает на вопрос, которого не было видно из четырёх карточек:
ГДЕ теряются люди. У каждого этапа подписано, какая доля дошла с предыдущего.

**Светофор** заменяет таблицу на два десятка строк: плитка на район с цветом
по порогам читается как «у кого плохо», а не как список чисел. Цвет берут те
же пороги, что и остальные виджеты, — своя шкала цветов рядом с общей
означала бы, что красный на соседних виджетах значит разное.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db

PLAN_ALERTS = [
    {"op": "lt", "value": 90, "level": "danger", "label": "ниже 90 % плана"},
    {"op": "lt", "value": 100, "level": "warn", "label": "план не выполнен"},
    {"op": "gte", "value": 100, "level": "good", "label": "план выполнен"},
]


async def _page(client, headers, name):
    did = (await client.post("/dashboards", headers=headers, json={"name": name})).json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=headers,
                             json={"name": "Стр"})).json()["id"]
    return did, pid


async def _cleanup(did):
    async with db.acquire() as conn:
        await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
        await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
        await conn.execute("delete from dashboards where id=$1::uuid", did)


async def _data(client, headers, pid, body):
    r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return (await client.get(f"/widgets/{r.json()['id']}/data", headers=headers)).json()


async def test_funnel_shows_where_people_are_lost(client, admin_headers, seed_dataset):
    """Главное в воронке — доля, дошедшая с предыдущего этапа, и потеря числом."""
    did, pid = await _page(client, admin_headers, "ztest_funnel")
    try:
        d = await _data(client, admin_headers, pid, {
            "name": "Воронка", "widget_type": "funnel",
            "config": {"dataset_code": seed_dataset["code"], "value_fields": ["plan", "fact"]}})
        assert d["type"] == "funnel" and len(d["stages"]) == 2
        first, second = d["stages"]
        assert first["value"] == seed_dataset["plan_sum"]            # 180
        assert first["pct_of_prev"] is None, "у первого этапа не с чем сравнивать"
        # Факт 173 из плана 180 → дошли 96,1 %, потеря 7.
        assert round(second["pct_of_prev"], 1) == 96.1
        assert second["lost"] == first["value"] - second["value"]
        assert round(second["pct_of_first"], 1) == 96.1
    finally:
        await _cleanup(did)


async def test_funnel_needs_at_least_two_stages(client, admin_headers, seed_dataset):
    """Один этап — не воронка: «сколько дошло» существует только при переходе."""
    did, pid = await _page(client, admin_headers, "ztest_funnel_one")
    try:
        r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "Плохая воронка", "widget_type": "funnel",
            "config": {"dataset_code": seed_dataset["code"], "value_fields": ["plan"]}})
        data = await client.get(f"/widgets/{r.json()['id']}/data", headers=admin_headers)
        assert data.status_code == 400
        assert "два этапа" in data.json()["detail"]
    finally:
        await _cleanup(did)


async def test_status_grid_colors_rows_by_plan(client, admin_headers, seed_dataset):
    """Плитка на строку: цвет по проценту выполнения, теми же порогами."""
    did, pid = await _page(client, admin_headers, "ztest_grid")
    try:
        d = await _data(client, admin_headers, pid, {
            "name": "Светофор", "widget_type": "status_grid",
            "config": {"dataset_code": seed_dataset["code"], "value_field": "fact",
                       "plan_field": "plan", "alerts": PLAN_ALERTS}})
        assert d["compared_to_plan"] is True
        by_row = {c["label"]: c for c in d["cells"]}
        # Фикстура: Паспорт 90/100 = 90 %, ИНН 55/50 = 110 %, СНИЛС 28/30 = 93,3 %.
        assert by_row["Паспорт"]["level"] == "warn", "90 % — план не выполнен, но не провал"
        assert by_row["ИНН"]["level"] == "good"
        assert round(by_row["СНИЛС"]["pct"], 1) == 93.3
        assert by_row["ИНН"]["plan"] == 50, "план показываем рядом: без него процент не проверить"
    finally:
        await _cleanup(did)


async def test_status_grid_works_without_plan(client, admin_headers, seed_dataset):
    """Без плана светофор красит по самому значению, а не падает."""
    did, pid = await _page(client, admin_headers, "ztest_grid_noplan")
    try:
        d = await _data(client, admin_headers, pid, {
            "name": "Светофор без плана", "widget_type": "status_grid",
            "config": {"dataset_code": seed_dataset["code"], "value_field": "fact",
                       "alerts": [{"op": "lt", "value": 50, "level": "danger"}]}})
        assert d["compared_to_plan"] is False
        by_row = {c["label"]: c for c in d["cells"]}
        assert by_row["СНИЛС"]["level"] == "danger", "28 < 50"
        assert by_row["Паспорт"]["level"] is None, "90 порога не пересекает"
        assert all(c["pct"] is None for c in d["cells"])
    finally:
        await _cleanup(did)
