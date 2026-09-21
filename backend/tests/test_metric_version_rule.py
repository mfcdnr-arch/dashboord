"""Какая версия формулы считается действующей — правило ОДНО на систему.

До 21.09.2026 это правило было скопировано в тринадцать мест восьми модулей и
в ДВУХ несовпадающих редакциях: одна ставила черновик наравне со снятой с
эксплуатации версией, другая — впереди неё. Обе редакции соседствовали даже
внутри `metrics/service.py`: каталог источников отдавал формулу одной версии,
а список значений считал по другой.

Сегодня расхождение не проявляется — `deprecated` проставляется только при
одобрении новой версии, поэтому рядом всегда есть `approved`, который
выигрывает в обеих редакциях. То есть это не живой дефект, а мина: стоит
появиться переходу «снять с эксплуатации, не одобряя замену» — и подсказка ⓘ
начнёт называть одну формулу, а виджет считать по другой. Молча.

Здесь проверяется ровно то, чего не хватало: что все потребители выбирают одну
и ту же версию в случае, который старые редакции разводили, и что своей копии
правила больше ни у кого нет.
"""
import ast
import pathlib

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.dashboards._explain import explain_widgets
from app.modules.metrics.versions import best_version_order

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


async def test_all_consumers_pick_the_same_version(client, admin_headers, seed_dataset, ids):
    """Черновик побеждает снятую с эксплуатации версию — и так во всех местах.

    Расстановка подобрана так, что СТАРЫЕ редакции дали бы РАЗНЫЕ ответы:
    у `deprecated` номер версии больше, поэтому редакция «… else 2» взяла бы
    именно её, а редакция «… draft then 2 else 3» — черновик. Числа формул
    различаются, поэтому подмена версии видна значением, а не только статусом.

    Штатного перехода «снять с эксплуатации, не одобряя замену» в системе нет,
    поэтому вторая версия переводится прямым запросом. Это и есть смысл теста:
    инвариант обязан держаться независимо от того, какие переходы существуют
    сегодня, — иначе он снова разойдётся молча.
    """
    m = await client.post("/metrics", headers=admin_headers,
                          json={"code": "ztest_ver_rule", "name": "ztest правило версий"})
    assert m.status_code in (200, 201), m.text
    mid = m.json()["id"]
    try:
        v1 = await client.post(f"/metrics/{mid}/versions", headers=admin_headers,
                               json={"formula": f"SUM(field('{seed_dataset['code']}','plan'))", "unit": "шт"})
        v2 = await client.post(f"/metrics/{mid}/versions", headers=admin_headers,
                               json={"formula": f"SUM(field('{seed_dataset['code']}','fact'))", "unit": "шт"})
        assert v2.status_code in (200, 201), v2.text
        async with db.acquire() as conn:
            await conn.execute("update metric_versions set status='deprecated' where id=$1::uuid",
                               v2.json()["version_id"])
            nos = await conn.fetch(
                "select version_no, status::text from metric_versions where metric_id=$1::uuid "
                "order by version_no", mid)
        # у снятой версии номер БОЛЬШЕ — иначе случай не различал бы редакции
        assert [r["status"] for r in nos] == ["draft", "deprecated"], nos
        assert nos[1]["version_no"] > nos[0]["version_no"]

        plan, fact = seed_dataset["plan_sum"], sum(seed_dataset["fact"])
        assert plan != fact, "фикстура должна давать разные суммы, иначе подмена версии незаметна"

        # 1. Список показателей (metrics/service.list_metric_values)
        r = await client.get("/metrics/values", headers=admin_headers)
        item = next(i for i in r.json()["items"] if i["code"] == "ztest_ver_rule")
        assert item["value"] == plan, f"список значений взял не ту версию: {item}"
        assert item["status"] == "draft"

        # 2. Каталог источников конструктора (metrics/service.list_data_sources)
        src = await client.get("/metrics/data-sources", headers=admin_headers)
        cat = next(i for i in src.json()["metrics"] if i["code"] == "ztest_ver_rule")
        assert "'plan'" in (cat["formula"] or ""), f"каталог источников показывает другую формулу: {cat}"

        # 3. Сам виджет (dashboards/_widgetsources._metric_value)
        w = await client.post("/widgets/preview", headers=admin_headers,
                              json={"widget_type": "kpi", "name": "T",
                                    "config": {"metric_code": "ztest_ver_rule"}})
        assert w.status_code == 200, w.text
        assert w.json()["value"] == plan, f"виджет посчитал по другой версии: {w.json()}"

        # 4. Подсказка ⓘ (dashboards/_explain) — та же версия и её состояние словами
        async with db.acquire() as conn:
            tips = await explain_widgets(conn, ids["org"], [
                {"id": "00000000-0000-0000-0000-000000000001", "widget_type": "kpi",
                 "config": {"metric_code": "ztest_ver_rule"}}])
        tip = tips["00000000-0000-0000-0000-000000000001"]
        assert "'plan'" in tip, f"подсказка называет другую формулу: {tip}"
        assert "черновик" in tip, f"состояние версии обязано быть названо: {tip}"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from metric_versions where metric_id=$1::uuid", mid)
            await conn.execute("delete from metrics where id=$1::uuid", mid)


async def test_retired_version_is_used_but_named(client, admin_headers, seed_dataset, ids):
    """Снятая версия НЕ исключается из расчёта, но названа словами.

    Исключить её значило бы получить «запрет без выхода»: у показателя, где не
    осталось ни одной живой версии, виджет ответил бы отказом вместо числа, и
    сделать с этим на экране было бы нечего. Вместо этого считаем по ней и
    прямо говорим, что действующей версии нет.
    """
    m = await client.post("/metrics", headers=admin_headers,
                          json={"code": "ztest_ver_dead", "name": "ztest только снятая"})
    mid = m.json()["id"]
    try:
        v = await client.post(f"/metrics/{mid}/versions", headers=admin_headers,
                              json={"formula": f"SUM(field('{seed_dataset['code']}','plan'))"})
        async with db.acquire() as conn:
            await conn.execute("update metric_versions set status='deprecated' where id=$1::uuid",
                               v.json()["version_id"])
            tips = await explain_widgets(conn, ids["org"], [
                {"id": "00000000-0000-0000-0000-000000000002", "widget_type": "kpi",
                 "config": {"metric_code": "ztest_ver_dead"}}])

        w = await client.post("/widgets/preview", headers=admin_headers,
                              json={"widget_type": "kpi", "name": "T",
                                    "config": {"metric_code": "ztest_ver_dead"}})
        assert w.status_code == 200 and w.json()["value"] == seed_dataset["plan_sum"], w.text
        tip = tips["00000000-0000-0000-0000-000000000002"]
        assert "снята с эксплуатации" in tip, f"про снятую версию промолчали: {tip}"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from metric_versions where metric_id=$1::uuid", mid)
            await conn.execute("delete from metrics where id=$1::uuid", mid)


def test_order_covers_every_status():
    """Каждое состояние из enum названо явно, и порядок именно такой.

    `metric_status` — ENUM в БД (миграция 002). Появится шестое состояние —
    оно молча упадёт в хвост `else`, то есть окажется ниже архивной версии;
    тест не даст этому пройти незамеченным.
    """
    order = best_version_order()
    for i, status in enumerate(("approved", "validated", "draft", "deprecated")):
        assert f"when '{status}' then {i}" in order, f"{status} не на своём месте: {order}"
    assert order.endswith("mv.version_no desc")
    assert best_version_order("").endswith("version_no desc")
    assert "mv." not in best_version_order("")


def test_rule_lives_only_in_one_module():
    """Ни у кого нет своей копии правила.

    Смотрим строковые литералы КОДА, а не текст файла: объяснить порядок в
    комментарии — нормально, а составить свой `order by` мимо versions.py — нет.
    Ровно так же устроен страж заголовков адреса (test_proxy_headers).
    """
    guilty = []
    for path in APP.rglob("*.py"):
        if path.name == "versions.py" and path.parent.name == "metrics":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                first = (node.body or [None])[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                        and isinstance(first.value.value, str):
                    docs.add(id(first.value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                if "when 'approved' then" in node.value.lower():
                    guilty.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert not guilty, (
        "своя копия правила выбора версии формулы: " + ", ".join(guilty) +
        " — порядок задаёт metrics/versions.best_version_order()")
