"""Подборка «Руководителю» и автоописание дашборда (волна 1, шаг 1).

Общий список дашбордов устроен для того, кто их СОБИРАЕТ: поиск, фильтр по
папке, диапазон дат, статус публикации. Руководителю нужно другое — понять,
какой отчёт про что, и открыть его; для этого нужны описание и короткая
подборка.

Ключевое архитектурное решение, которое проверяют эти тесты: **второй системы
прав нет**. Флаг `featured` отвечает только за состав подборки, а КТО что
видит, решают те же гранты, что и в общем списке. Иначе рядом с грантами
появился бы второй источник правды о доступе — и рано или поздно они
разошлись бы, показав руководителю чужой отчёт.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db


async def test_featured_respects_grants_not_its_own_rules(client, admin_headers, viewer):
    """Отметка в подборку НЕ выдаёт доступ: без гранта зритель ничего не видит."""
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_feat_dash"})
    did = r.json()["id"]
    try:
        await client.post(f"/dashboards/{did}/featured", headers=admin_headers, json={"featured": True})
        await client.post(f"/dashboards/{did}/publish", headers=admin_headers, json={})

        seen = (await client.get("/dashboards/featured", headers=viewer["headers"])).json()["items"]
        assert not any(i["id"] == did for i in seen), \
            "подборка не должна открывать доступ — это делают только гранты"

        await client.post(f"/dashboards/{did}/grants", headers=admin_headers,
                          json={"grantee_type": "user", "user_id": viewer["id"]})
        seen = (await client.get("/dashboards/featured", headers=viewer["headers"])).json()["items"]
        assert any(i["id"] == did for i in seen), "с грантом отчёт появляется в подборке"

        # И наоборот: снятая отметка убирает отчёт из подборки, доступ при этом
        # остаётся — человек по-прежнему открывает его из общего списка.
        await client.post(f"/dashboards/{did}/featured", headers=admin_headers, json={"featured": False})
        seen = (await client.get("/dashboards/featured", headers=viewer["headers"])).json()["items"]
        assert not any(i["id"] == did for i in seen)
        full = (await client.get("/dashboards?limit=200", headers=viewer["headers"])).json()["items"]
        assert any(i["id"] == did for i in full), "доступ снимается грантом, а не отметкой"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from access_grants where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_featured_flag_visible_in_list(client, admin_headers):
    """Админ должен видеть в общем списке, что уже входит в подборку."""
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_feat_flag"})
    did = r.json()["id"]
    try:
        await client.post(f"/dashboards/{did}/featured", headers=admin_headers, json={"featured": True})
        items = (await client.get("/dashboards?limit=200", headers=admin_headers)).json()["items"]
        row = next(i for i in items if i["id"] == did)
        assert row["featured"] is True
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_featured_is_staff_only(client, viewer, admin_headers):
    """Состав подборки задаёт управляющий, а не любой, кто её видит."""
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_feat_acl"})
    did = r.json()["id"]
    try:
        assert (await client.post(f"/dashboards/{did}/featured", headers=viewer["headers"],
                                  json={"featured": True})).status_code == 403
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_description_draft_describes_the_real_content(client, admin_headers, seed_dataset):
    """Черновик описания собирается по СОСТАВУ дашборда, а не из шаблона."""
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_descr"})
    did = r.json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                             json={"name": "Обзор"})).json()["id"]
    try:
        for name, field in (("Всего заявлений", "plan"), ("Исполнено", "fact")):
            await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
                "name": name, "widget_type": "kpi",
                "config": {"dataset_code": seed_dataset["code"], "value_field": field}})

        d = (await client.get(f"/dashboards/{did}/description-draft", headers=admin_headers)).json()
        assert "Всего заявлений" in d["draft"] and "Исполнено" in d["draft"]
        assert "карточки показателей (2)" in d["draft"]
        # У фикстуры два отчётных периода — про обновление сказать обязаны:
        # руководитель должен знать, живые перед ним цифры или снимок.
        assert "2 периода" in d["draft"] and "обновляются сами" in d["draft"]
        assert d["current"] is None, "в БД черновик молча не пишется"
        assert d["facts"]["widgets"] == 2 and d["facts"]["datasets"] == [seed_dataset["code"]]
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_description_draft_does_not_repeat_one_metric_in_three_slices(client, admin_headers, seed_dataset):
    """Один показатель в трёх разрезах — это ОДИН показатель.

    Имена госформ различаются только хвостом («· Факт · нарастающим итогом»,
    «· за отчётную неделю»), и без дедупликации описание превращалось в
    «Количество обращений, Количество обращений, Количество обращений».
    """
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_descr_dup"})
    did = r.json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                             json={"name": "Обзор"})).json()["id"]
    try:
        for slice_name in ("нарастающим итогом", "текущий месяц", "за отчётную неделю"):
            await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
                "name": f"Количество обращений · Факт · {slice_name}", "widget_type": "kpi",
                "config": {"dataset_code": seed_dataset["code"], "value_field": "plan"}})

        draft = (await client.get(f"/dashboards/{did}/description-draft",
                                  headers=admin_headers)).json()["draft"]
        assert draft.count("Количество обращений") == 1, draft
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_featured_tiles_show_numbers_and_growth(client, admin_headers, seed_dataset, viewer):
    """На плитке подборки видны главные цифры и прирост — без открывания отчёта.

    Прирост считается, даже если у самой карточки он выключен: на дашбордах,
    собранных до появления этой настройки, руководитель иначе видел бы голое
    число, которое не отвечает на его единственный вопрос — «хорошо или плохо».
    """
    r = await client.post("/dashboards", headers=admin_headers,
                          json={"name": "ztest_feat_tiles", "force": True})
    did = r.json()["id"]
    try:
        page = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "Обзор"})
        pid = page.json()["id"]
        # compare_prev НЕ включаем — именно этот случай и проверяем.
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "ztest Сумма плана", "widget_type": "kpi",
                                "config": {"dataset_code": seed_dataset["code"], "value_field": "plan"}})
        await client.post(f"/dashboards/{did}/featured", headers=admin_headers, json={"featured": True})

        items = (await client.get("/dashboards/featured", headers=admin_headers)).json()["items"]
        tile = next(i for i in items if i["id"] == did)
        assert tile["highlights"], "плитка обязана показывать цифры"
        h = tile["highlights"][0]
        assert h["value"] == seed_dataset["plan_sum"], "значение считается тем же кодом, что и виджет"
        assert h["delta_pct"] is not None, "прирост считается, даже когда у карточки он выключен"

        # Видимость: без гранта зритель не получает ни отчёта, ни его цифр.
        seen = (await client.get("/dashboards/featured", headers=viewer["headers"])).json()["items"]
        assert all(i["id"] != did for i in seen)
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from access_grants where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_featured_candidates_advise_but_do_not_decide(client, admin_headers, seed_dataset, viewer):
    """Система советует по проверяемым признакам, решение остаётся за человеком.

    Совет строится только на том, что можно проверить: опубликован ли отчёт,
    есть ли в нём цифры и есть ли кому его смотреть. «Полезно руководителю» —
    суждение, поэтому галочки ставит администратор, а не система.
    """
    r = await client.post("/dashboards", headers=admin_headers,
                          json={"name": "ztest_feat_cand", "force": True,
                                "description": "Отчёт для проверки советов"})
    did = r.json()["id"]
    try:
        page = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "Обзор"})
        await client.post(f"/dashboard-pages/{page.json()['id']}/widgets", headers=admin_headers,
                          json={"name": "ztest Показатель", "widget_type": "kpi",
                                "config": {"dataset_code": seed_dataset["code"], "value_field": "plan"}})

        items = (await client.get("/dashboards/featured/candidates", headers=admin_headers)).json()["items"]
        row = next(i for i in items if i["id"] == did)
        assert row["featured"] is False
        assert row["recommended"] is False, "черновик советовать нельзя — руководителю попадёт неутверждённое"
        assert any("не опубликован" in b for b in row["blockers"])

        await client.post(f"/dashboards/{did}/publish", headers=admin_headers, json={})
        row = next(i for i in (await client.get("/dashboards/featured/candidates",
                                                headers=admin_headers)).json()["items"] if i["id"] == did)
        assert row["recommended"] is True, "опубликован, есть цифры и есть кому смотреть"
        assert row["number_widgets"] == 1
        assert row["visible_to"] >= 1, "нужно показывать, скольким людям отчёт виден"

        # Пакетное применение: отметили — попал в подборку.
        await client.post("/dashboards/featured/bulk", headers=admin_headers,
                          json={"featured": [did], "unfeatured": []})
        seen = (await client.get("/dashboards/featured", headers=admin_headers)).json()["items"]
        assert any(i["id"] == did for i in seen)

        # Повтор не ошибка и не дубль: панель шлёт разницу целиком.
        again = await client.post("/dashboards/featured/bulk", headers=admin_headers,
                                  json={"featured": [did], "unfeatured": []})
        assert again.status_code == 200 and again.json()["featured"] == 0

        # Настройка состава — не для зрителя.
        assert (await client.get("/dashboards/featured/candidates",
                                 headers=viewer["headers"])).status_code == 403
        assert (await client.post("/dashboards/featured/bulk", headers=viewer["headers"],
                                  json={"featured": [did]})).status_code == 403
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_versions where dashboard_id=$1::uuid", did)
            await conn.execute("delete from publication_requests where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)
