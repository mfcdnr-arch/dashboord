"""«Куда посмотреть дальше» от конкретной цифры (п. 1 списка заказчика).

Дашборд отвечает «сколько», а следующий вопрос руководителя — «почему
столько?». Меню собирается СЕРВЕРОМ из того, что система уже знает о виджетах:
связки не настраиваются руками, потому что настроенная руками связь устаревает
молча — форму меняют, показатель переименовывают, а пункт ведёт в никуда.

Главное, что проверяется здесь, — **видимость**: «где ещё есть этот показатель»
не должно оглашать чужие отчёты. Даже одни названия говорят, какие показатели
за кем закреплены.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db


async def _mk_widget(client, headers, did, page_id, name, cfg, wtype="kpi"):
    r = await client.post(f"/dashboard-pages/{page_id}/widgets", headers=headers,
                          json={"name": name, "widget_type": wtype, "config": cfg})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _dash(client, headers, name):
    r = await client.post("/dashboards", headers=headers, json={"name": name})
    did = r.json()["id"]
    r = await client.post(f"/dashboards/{did}/pages", headers=headers, json={"name": "Обзор"})
    return did, r.json()["id"]


async def _drop(dids):
    async with db.acquire() as conn:
        for did in dids:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from access_grants where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from audit_log where entity_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_related_finds_same_indicator_and_siblings(client, admin_headers, seed_dataset):
    did, pid = await _dash(client, admin_headers, "ztest_rel_a")
    try:
        cfg = {"dataset_code": seed_dataset["code"], "value_field": "plan"}
        main = await _mk_widget(client, admin_headers, did, pid, "ztest Карточка плана", cfg)
        # Тот же показатель другим видом — он и должен найтись.
        await _mk_widget(client, admin_headers, did, pid, "ztest Столбцы плана", cfg, "bar")
        # Другая графа той же формы — это «сосед», а не «то же самое».
        await _mk_widget(client, admin_headers, did, pid, "ztest Факт",
                         {"dataset_code": seed_dataset["code"], "value_field": "fact"})

        r = await client.get(f"/widgets/{main}/related", headers=admin_headers)
        assert r.status_code == 200, r.text
        data = r.json()

        assert data["subject"]["kind"] == "field"
        names = [x["widget_name"] for x in data["elsewhere"]]
        assert "ztest Столбцы плана" in names, "тот же показатель другим видом обязан находиться"
        assert "ztest Факт" not in names, "другая графа — это сосед, а не та же величина"
        assert main not in [x["widget_id"] for x in data["elsewhere"]], "сам себя виджет не предлагает"

        # Динамика: у фикстуры два выпуска, движение построить можно.
        assert data["dynamics"]["available"] is True
        assert data["dynamics"]["periods"] == 2
    finally:
        await _drop([did])


async def test_related_does_not_leak_other_peoples_dashboards(client, admin_headers, viewer, seed_dataset):
    """Зритель не должен узнать о чужом отчёте даже по названию виджета."""
    mine, mine_page = await _dash(client, admin_headers, "ztest_rel_mine")
    other, other_page = await _dash(client, admin_headers, "ztest_rel_other")
    try:
        cfg = {"dataset_code": seed_dataset["code"], "value_field": "plan"}
        w_mine = await _mk_widget(client, admin_headers, mine, mine_page, "ztest Мой план", cfg)
        await _mk_widget(client, admin_headers, other, other_page, "ztest ЧУЖОЙ план", cfg)

        # Зрителю открыт только первый дашборд.
        await client.post(f"/dashboards/{mine}/publish", headers=admin_headers, json={})
        await client.post(f"/dashboards/{mine}/grants", headers=admin_headers,
                          json={"grantee_type": "user", "user_id": viewer["id"]})

        seen = (await client.get(f"/widgets/{w_mine}/related", headers=viewer["headers"])).json()
        names = [x["widget_name"] for x in seen["elsewhere"]]
        assert "ztest ЧУЖОЙ план" not in names, "чужой отчёт не должен всплывать даже названием"

        # Администратор видит оба — правило про видимость, а не про сокрытие.
        names_admin = [x["widget_name"] for x in
                       (await client.get(f"/widgets/{w_mine}/related", headers=admin_headers)).json()["elsewhere"]]
        assert "ztest ЧУЖОЙ план" in names_admin
    finally:
        await _drop([mine, other])


async def test_related_on_invisible_widget_is_404(client, viewer, admin_headers, seed_dataset):
    did, pid = await _dash(client, admin_headers, "ztest_rel_hidden")
    try:
        wid = await _mk_widget(client, admin_headers, did, pid, "ztest Скрытый",
                               {"dataset_code": seed_dataset["code"], "value_field": "plan"})
        r = await client.get(f"/widgets/{wid}/related", headers=viewer["headers"])
        assert r.status_code == 404, "недоступный виджет не должен рассказывать о себе"
    finally:
        await _drop([did])


async def test_related_for_metric_widget_names_the_metric(client, admin_headers, ids, seed_dataset):
    """У виджета по метрике предмет — показатель, а не графа формы."""
    r = await client.post("/metrics", headers=admin_headers,
                          json={"code": "ztest_rel_metric", "name": "ztest Показатель"})
    assert r.status_code in (200, 201), r.text
    mid = r.json()["id"]
    did, pid = await _dash(client, admin_headers, "ztest_rel_metric_dash")
    try:
        await client.post(f"/metrics/{mid}/versions", headers=admin_headers,
                          json={"formula": f"SUM(field('{seed_dataset['code']}','plan'))", "unit": "шт"})
        wid = await _mk_widget(client, admin_headers, did, pid, "ztest Карточка показателя",
                               {"metric_code": "ztest_rel_metric"})
        data = (await client.get(f"/widgets/{wid}/related", headers=admin_headers)).json()
        assert data["subject"]["kind"] == "metric"
        assert data["subject"]["name"] == "ztest Показатель"
        # Датасета в конфиге нет, поэтому про соседей и динамику честно молчим.
        assert data["siblings"] == []
        assert data["dynamics"]["available"] is False
    finally:
        await _drop([did])
        async with db.acquire() as conn:
            await conn.execute("delete from metric_versions where metric_id=$1::uuid", mid)
            await conn.execute("delete from metrics where id=$1::uuid", mid)


async def test_siblings_say_whether_they_are_already_shown(client, admin_headers, seed_dataset):
    """У соседа два разных состояния, и путать их нельзя.

    Если карточка соседней графы на дашборде уже есть — к ней переходят;
    если нет — заводят. Одинаковая кнопка на оба случая плодила бы вторую
    карточку того же показателя рядом с первой.
    """
    did, pid = await _dash(client, admin_headers, "ztest_sib_state")
    # Фикстура заводит значения в обход конвейера распознавания и НЕ создаёт
    # справочник полей объекта, а «соседи» строятся именно по нему.
    async with db.acquire() as conn:
        obj = await conn.fetchval(
            "select object_id from dataset_releases where code=$1 limit 1", seed_dataset["code"])
        for code, name in (("plan", "План"), ("fact", "Факт")):
            await conn.execute(
                "insert into canonical_fields(object_id, code, name) values($1,$2,$3) "
                "on conflict do nothing", obj, code, name)
    try:
        cfg = {"dataset_code": seed_dataset["code"], "value_field": "plan"}
        main = await _mk_widget(client, admin_headers, did, pid, "ztest План", cfg)

        # Пока «fact» ничем не показан — сосед предлагается к заведению.
        r = (await client.get(f"/widgets/{main}/related", headers=admin_headers)).json()
        fact = next(s for s in r["siblings"] if s["field"] == "fact")
        assert "shown_widget_id" not in fact
        # Куда класть новую карточку — та же страница, с которой смотрят.
        assert r["page_id"] == pid and r["dashboard_id"] == did

        # Завели карточку факта — сосед должен перестать предлагаться и стать
        # ссылкой на существующий виджет.
        shown = await _mk_widget(client, admin_headers, did, pid, "ztest Факт", 
                                 {"dataset_code": seed_dataset["code"], "value_field": "fact"})
        r = (await client.get(f"/widgets/{main}/related", headers=admin_headers)).json()
        fact = next(s for s in r["siblings"] if s["field"] == "fact")
        assert fact.get("shown_widget_id") == shown
        assert fact.get("shown_widget_name") == "ztest Факт"
        assert fact.get("shown_page_id") == pid
    finally:
        await _drop([did])
        async with db.acquire() as conn:
            await conn.execute(
                "delete from canonical_fields where object_id=(select object_id from dataset_releases "
                "where code=$1 limit 1) and code = any($2::text[])", seed_dataset["code"], ["plan", "fact"])
