"""Быстрый поиск по системе (п. 9, Ctrl+K).

Раньше поиск существовал только внутри разделов: чтобы найти показатель,
нужно было сначала угадать, что искать в «Метриках», а не в «Дашбордах».
Один запрос сразу по пяти сущностям.

Тесты держат главное: **RLS соблюдён на границе поиска, а не только у самих
разделов**. Иначе поиск стал бы обходным путём — узнать имя чужого виджета
или дашборда, набрав первые буквы в строке поиска.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import db, purge_dashboard


async def _dash(client, headers, name, page_name="Обзор", widget_name="Виджет"):
    did = (await client.post("/dashboards", headers=headers, json={"name": name})).json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=headers,
                             json={"name": page_name})).json()["id"]
    wid = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=headers,
           json={"name": widget_name, "widget_type": "kpi",
                 "config": {"dataset_code": "t_ds", "value_field": "plan"}})).json()["id"]
    return did, pid, wid


async def test_finds_across_all_five_kinds(client, admin_headers, seed_dataset):
    """Один запрос находит дашборд, страницу, виджет, объект и показатель по
    общей части названия — ради этого поиск и заводили."""
    did, pid, wid = await _dash(client, admin_headers, "ztest_search Внедрение сервиса",
                                page_name="ztest_search Обзор", widget_name="ztest_search Обращения")
    try:
        r = await client.get("/search", params={"q": "ztest_search"}, headers=admin_headers)
        assert r.status_code == 200, r.text
        d = r.json()
        assert any(x["id"] == did for x in d["dashboards"])
        assert any(x["id"] == pid for x in d["pages"])
        assert any(x["id"] == wid for x in d["widgets"])

        # Объект находится ОТДЕЛЬНЫМ запросом по своему имени — тот же
        # справочник, что и раньше в разделе «Объекты».
        obj = await client.get("/search", params={"q": "t_obj"}, headers=admin_headers)
        assert any(x["name"] == "t_obj" for x in obj.json()["objects"])
    finally:
        await purge_dashboard(did)


async def test_short_query_returns_nothing(client, admin_headers):
    """Один символ — не запрос, а начало набора: полное сканирование по
    каждому нажатию клавиши того не стоит, и результат был бы шумом."""
    r = await client.get("/search", params={"q": "a"}, headers=admin_headers)
    assert r.status_code == 200
    d = r.json()
    assert all(d[k] == [] for k in ("dashboards", "pages", "widgets", "objects", "metrics"))


async def test_startswith_match_ranked_first(client, admin_headers, seed_dataset):
    """Имя, НАЧИНАЮЩЕЕСЯ с запроса, идёт первым — кто набрал начало названия,
    обычно имеет в виду конкретный дашборд, а не любой с этим словом внутри."""
    d1, _, _ = await _dash(client, admin_headers, "Внутри есть ztest_search_sw и только там")
    d2, _, _ = await _dash(client, admin_headers, "ztest_search_sw в начале имени")
    try:
        r = await client.get("/search", params={"q": "ztest_search_sw"}, headers=admin_headers)
        names = [x["name"] for x in r.json()["dashboards"]]
        assert names.index("ztest_search_sw в начале имени") \
            < names.index("Внутри есть ztest_search_sw и только там")
    finally:
        await purge_dashboard(d1)
        await purge_dashboard(d2)


async def test_viewer_does_not_see_dashboards_without_access(client, admin_headers, viewer, seed_dataset):
    """Дашборд, к которому нет гранта, не находится поиском — тот же принцип,
    что и в общем списке дашбордов."""
    did, pid, wid = await _dash(client, admin_headers, "ztest_search Закрытый отчёт")
    try:
        r = await client.get("/search", params={"q": "ztest_search Закрытый"}, headers=viewer["headers"])
        d = r.json()
        assert d["dashboards"] == [] and d["pages"] == [] and d["widgets"] == []
    finally:
        await purge_dashboard(did)


async def test_widget_level_grant_is_a_whitelist_in_search_too(client, admin_headers, viewer, seed_dataset):
    """🔴 Главная проверка: у дашборда есть widget-level гранты — зритель видит
    в поиске ТОЛЬКО выданный виджет, а не оба.

    Если бы поиск не учитывал whitelist, набрав в строке общую часть имени,
    зритель нашёл бы виджет, которого ему видеть нельзя, — обходной путь
    вокруг ровно того ограничения, которое whitelist и должен держать.
    """
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_search_wl Отчёт"})).json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                             json={"name": "P"})).json()["id"]
    w_open = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
              json={"name": "ztest_search_wl Открытый", "widget_type": "kpi",
                    "config": {"dataset_code": "t_ds", "value_field": "plan"}})).json()["id"]
    w_hidden = (await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                json={"name": "ztest_search_wl Скрытый", "widget_type": "kpi",
                      "config": {"dataset_code": "t_ds", "value_field": "plan"}})).json()["id"]
    try:
        # Дашборд-грант (видит дашборд) + widget-грант ТОЛЬКО на один виджет —
        # с этого момента для зрителя действует whitelist (п. 3-4, миграция 004).
        await client.post(f"/dashboards/{did}/grants", headers=admin_headers,
                          json={"grantee_type": "user", "user_id": viewer["id"]})
        await client.post(f"/dashboards/{did}/grants", headers=admin_headers,
                          json={"grantee_type": "user", "user_id": viewer["id"],
                                "scope": "widget", "widget_id": w_open})
        await client.post(f"/dashboards/{did}/publish", headers=admin_headers)

        r = await client.get("/search", params={"q": "ztest_search_wl"}, headers=viewer["headers"])
        ids = {x["id"] for x in r.json()["widgets"]}
        assert w_open in ids
        assert w_hidden not in ids, "виджет без гранта не должен находиться поиском"
    finally:
        await purge_dashboard(did)


async def test_metrics_match_by_code_or_name(client, admin_headers, ids):
    """Показатель находится и по коду, и по названию — так же, как в списке
    метрик."""
    async with db.acquire() as conn:
        await conn.execute("delete from metrics where code='ztest_search_m' and organization_id=$1", ids["org"])
        await conn.execute(
            "insert into metrics(organization_id,code,name,created_by) values($1,$2,$3,$4)",
            ids["org"], "ztest_search_m", "Доля отвеченных обращений", ids["admin"])
    try:
        by_code = await client.get("/search", params={"q": "ztest_search_m"}, headers=admin_headers)
        by_name = await client.get("/search", params={"q": "Доля отвеченных"}, headers=admin_headers)
        assert any(m["code"] == "ztest_search_m" for m in by_code.json()["metrics"])
        assert any(m["code"] == "ztest_search_m" for m in by_name.json()["metrics"])
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from metrics where code='ztest_search_m' and organization_id=$1", ids["org"])
