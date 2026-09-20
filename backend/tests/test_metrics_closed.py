"""Слой показателей закрыт от рядового пользователя (20.09.2026).

Модель доступа в системе построена на уровне ДАШБОРДОВ (гранты, whitelist
виджетов) и СТРОК (`data_row_acl`). У показателей своей проверки нет вовсе —
только принадлежность к организации, — поэтому два эндпоинта, стоявшие под
`get_current_user`, давали обход всей модели: цепочка «поиск → показатель →
версия → значение» отдавала зрителю с доступом к ОДНОМУ дашборду тексты
формул и вычисленные значения всех KPI организации.

Проверяется именно утечка СОДЕРЖИМОГО, а не код ответа: тест, который
смотрит только на 403, пройдёт и тогда, когда данные утекут другим путём.

Разделы «Метрики» и «Объекты» помечены `staffOnly` в интерфейсе, поэтому
закрытие ничего не отнимает у зрителя — у него этих экранов нет.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db

# 403 — роль не подходит; 404 — «не существует» для этого пользователя.
# Оба означают «не пустили»; важно лишь, чтобы не было 200 с данными.
DENIED = {403, 404}

FORMULA_MARK = "ztest_secret_field"


async def test_viewer_cannot_read_metric_formula_or_value(client, admin_headers, viewer, seed_dataset):
    """Карточка показателя и значение версии — только управляющим."""
    m = await client.post("/metrics", headers=admin_headers,
                          json={"code": "ztest_closed_metric", "name": "ztest закрытый показатель"})
    mid = m.json()["id"]
    try:
        v = await client.post(f"/metrics/{mid}/versions", headers=admin_headers,
                              json={"formula": f"SUM(field('{seed_dataset['code']}','plan'))", "unit": "шт"})
        assert v.status_code == 201, v.text
        vid = v.json()["version_id"]
        vh = viewer["headers"]

        # 1. Карточка показателя: в ней лежит ТЕКСТ ФОРМУЛЫ — из чего считается
        #    цифра и на каких данных она построена.
        r = await client.get(f"/metrics/{mid}", headers=vh)
        assert r.status_code in DENIED, f"зритель прочитал карточку показателя: {r.status_code}"
        assert seed_dataset["code"] not in r.text, "имя набора данных утекло в тело отказа"

        ok = await client.get(f"/metrics/{mid}", headers=admin_headers)
        assert ok.status_code == 200 and ok.json()["versions"], "управляющему карточка обязана открываться"
        assert seed_dataset["code"] in ok.json()["versions"][0]["formula_expression"]

        # 2. Значение версии — самое опасное: оно ВЫЧИСЛЯЕТСЯ по данным мимо
        #    грантов на дашборды.
        r = await client.get(f"/metrics/versions/{vid}/value", headers=vh)
        assert r.status_code in DENIED, f"зритель получил вычисленное значение: {r.status_code}"
        assert str(seed_dataset["plan_sum"]) not in r.text, "значение показателя утекло в тело отказа"

        ok = await client.get(f"/metrics/versions/{vid}/value", headers=admin_headers)
        assert ok.status_code == 200 and ok.json()["value"] == seed_dataset["plan_sum"]

        # 3. Список показателей закрыт и раньше — держим это, чтобы правка
        #    «открыть список, он же безобидный» не прошла незамеченной.
        assert (await client.get("/metrics", headers=vh)).status_code in DENIED
        assert (await client.get("/metrics/values", headers=vh)).status_code in DENIED
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from metric_versions where metric_id=$1::uuid", mid)
            await conn.execute("delete from metrics where id=$1::uuid", mid)


async def test_every_metrics_route_requires_manage(client, admin_headers, viewer, seed_dataset):
    """Страж: ни один маршрут модуля показателей не открыт рядовому пользователю.

    🔴 Подставляются НАСТОЯЩИЕ идентификаторы, а не выдуманные, и это главное
    в этом тесте. С фейковым id открытый эндпоинт отвечает 404 «не найдено» —
    неотличимо от «не пустили», и страж молча проходит мимо ровно того, ради
    чего написан (проверено: с фейковым id он не поймал открытый
    `GET /metrics/{id}`). Существующие показатели дают 200 — и дефект виден.

    Список маршрутов берётся из OpenAPI, а не из `app.routes`: роутеры
    подключаются не на импорте, и `app.routes` знает лишь служебные пути
    (тот же приём, что в test_endpoints_require_auth)."""
    from app.main import app

    m = await client.post("/metrics", headers=admin_headers,
                          json={"code": "ztest_guard_metric", "name": "ztest страж"})
    mid = m.json()["id"]
    try:
        v = await client.post(f"/metrics/{mid}/versions", headers=admin_headers,
                              json={"formula": f"SUM(field('{seed_dataset['code']}','plan'))"})
        vid = v.json()["version_id"]

        spec = app.openapi()
        checked = 0
        for path, ops in spec["paths"].items():
            if not path.startswith("/metrics"):
                continue
            url = (path.replace("{metric_id}", mid).replace("{version_id}", vid)
                       .replace("{metric_code}", "ztest_guard_metric").replace("{version_no}", "1"))
            for method in ops:
                if method not in ("get", "post", "put", "patch", "delete"):
                    continue
                r = await client.request(method.upper(), url, headers=viewer["headers"], json={})
                assert r.status_code != 200, f"{method.upper()} {url} открыт рядовому пользователю"
                # 422 — параметры не разобраны, данные всё равно не выданы.
                assert r.status_code in DENIED | {422, 405}, f"{method.upper()} {url} → {r.status_code}"
                checked += 1
        assert checked >= 18, f"маршрутов модуля найдено всего {checked} — страж смотрит не туда"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from metric_versions where metric_id=$1::uuid", mid)
            await conn.execute("delete from metrics where id=$1::uuid", mid)


async def test_search_does_not_leak_metrics_and_objects_to_viewer(client, admin_headers, viewer, seed_dataset):
    """Поиск не обходит гейт раздела.

    Разделы «Метрики» и «Объекты» — `staffOnly`. Пока поиск отдавал их всем,
    зритель узнавал имена и коды всех показателей организации, набрав пару
    букв, а переход по найденному приводил его на закрытый экран."""
    m = await client.post("/metrics", headers=admin_headers,
                          json={"code": "ztestsearchmetric", "name": "ztest поисковый показатель"})
    mid = m.json()["id"]
    try:
        vh = viewer["headers"]
        r = await client.get("/search?q=ztest", headers=vh)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["metrics"] == [], "показатели утекли зрителю через поиск"
        assert "ztestsearchmetric" not in r.text, "код показателя виден зрителю в ответе поиска"

        # Объекты зрителю тоже не видны — проверяем ИХ запросом, иначе
        # пустой список ничего не доказывает (объект зовётся `t_obj` и под
        # запрос «ztest» не подходит вовсе).
        r = await client.get("/search?q=t_obj", headers=vh)
        assert r.status_code == 200 and r.json()["objects"] == [], "объекты утекли зрителю через поиск"

        # Управляющему поиск по-прежнему находит и то, и другое.
        found = (await client.get("/search?q=ztest", headers=admin_headers)).json()
        assert any(i["code"] == "ztestsearchmetric" for i in found["metrics"]), \
            "поиск перестал находить показатели управляющему"
        found_obj = (await client.get("/search?q=t_obj", headers=admin_headers)).json()
        assert any(i["name"] == "t_obj" for i in found_obj["objects"]), \
            "поиск перестал находить объекты управляющему"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from metrics where id=$1::uuid", mid)
