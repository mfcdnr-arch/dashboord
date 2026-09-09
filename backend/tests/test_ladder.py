"""Лестница уровней: фильтр по графам и ступени. Кусок 3.

Куски 1–2 научили систему видеть ступени и хранить подтверждённую иерархию;
здесь по ней ходят. Имена граф — настоящие, с формы РЦО: правило целиком про
устройство госформ.

🔴 Главное, что проверяется, — ветка сравнивается ПОЛНЫМИ сегментами. Сравнение
по началу строки выглядит проще и работает на первом же примере, но «Минюст»
поймал бы «Минюстиции», и ветка молча показала бы чужие цифры.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.dashboards._levels import (
    leaf_rows, narrow_cfg, step_rows, under,
)

SEP = " · "
TITLES = {
    "rr_reg_in": "Росреестр · Государственная регистрация прав · Принято, ед.",
    "rr_kad_in": "Росреестр · Государственный кадастровый учет · Принято, ед.",
    "mvd_in": "МВД · Регистрационный учет · Принято, ед.",
    "esia_in": "ЕСИА (260) · Принято, ед.",
    "itogo_in": "ИТОГО · Принято, ед.",
}


def test_branch_matches_whole_segments_not_a_prefix():
    """Ветка — это полные сегменты имени, а не начало строки."""
    assert under("Минюст · Апостиль · Принято, ед.", SEP, ["Минюст"])
    assert not under("Минюстиции · Что-то · Принято, ед.", SEP, ["Минюст"]), \
        "«Минюст» не должен ловить «Минюстиции»"
    # Пустой путь — корень, под ним лежит всё.
    assert under("что угодно · Принято, ед.", SEP, [])
    # Ветка глубже, чем само имя.
    assert not under("ЕСИА (260) · Принято, ед.", SEP, ["ЕСИА (260)", "Услуга"])


def test_narrow_keeps_only_the_branch_and_drops_the_total():
    """🔴 Свод из ветки выбрасывается: внутри «Росреестра» он даёт итог по ВСЕЙ форме.

    Оставь мы «ИТОГО · Принято, ед.», карточка ветки показала бы число всей
    формы под именем ведомства — правдоподобно и неверно.
    """
    cfg = {"dataset_code": "d", "value_fields": list(TITLES)}
    out = narrow_cfg(cfg, TITLES, SEP, ["Росреестр"])
    assert out["value_fields"] == ["rr_reg_in", "rr_kad_in"]
    assert "itogo_in" not in out["value_fields"]

    deep = narrow_cfg(cfg, TITLES, SEP, ["Росреестр", "Государственный кадастровый учет"])
    assert deep["value_fields"] == ["rr_kad_in"]


def test_widget_outside_the_branch_says_so_instead_of_showing_a_number():
    """Виджет, у которого в ветке не осталось граф, молчит, а не показывает чужое."""
    assert narrow_cfg({"value_field": "esia_in"}, TITLES, SEP, ["Росреестр"]) is None
    # Пара «план и факт»: выпала половина — сравнивать нечего.
    titles = {**TITLES, "plan": "Росреестр · План · Принято, ед.", "fact": "МВД · Факт · Принято, ед."}
    assert narrow_cfg({"plan_field": "plan", "fact_field": "fact"}, titles, SEP, ["Росреестр"]) is None
    # Без ветки конфигурация не трогается вовсе.
    cfg = {"value_fields": ["esia_in"]}
    assert narrow_cfg(cfg, TITLES, SEP, []) is cfg


def test_step_sums_children_and_averages_shares():
    """Ступень сворачивает детей той же свёрткой, что и карточка показателя."""
    vals = [
        {"name": TITLES["rr_reg_in"], "row_label": "Отд. 1", "value": 300},
        {"name": TITLES["rr_reg_in"], "row_label": "Отд. 2", "value": 141},
        {"name": TITLES["rr_kad_in"], "row_label": "Отд. 1", "value": 244},
        {"name": TITLES["mvd_in"], "row_label": "Отд. 1", "value": 448},
        {"name": TITLES["itogo_in"], "row_label": "Отд. 1", "value": 5426},
    ]
    kids = step_rows(vals, SEP, [], 0, "Принято, ед.")
    by = {k["value"]: k["total"] for k in kids}
    assert by == {"Росреестр": 685, "МВД": 448}, "свод в ступень не попадает"
    assert kids[0]["value"] == "Росреестр", "дети идут по величине"

    # Доли не складываются — усредняются (та же aggregate_series).
    shares = [{"name": "Росреестр · Услуга · Доля, %", "row_label": "Отд. 1", "value": 10},
              {"name": "Росреестр · Услуга · Доля, %", "row_label": "Отд. 2", "value": 20}]
    got = step_rows(shares, SEP, [], 0, "Доля, %")
    assert got[0]["total"] == 15 and got[0]["aggregate"] == "avg"


def test_bottom_step_respects_row_permissions():
    """Нижняя ступень не становится обходным путём к скрытым строкам."""
    vals = [{"name": TITLES["rr_reg_in"], "row_label": "Горловка", "value": 100},
            {"name": TITLES["rr_reg_in"], "row_label": "Донецк", "value": 200}]
    full = leaf_rows(vals, SEP, ["Росреестр"], "Принято, ед.")
    assert {r["value"] for r in full} == {"Горловка", "Донецк"}
    limited = leaf_rows(vals, SEP, ["Росреестр"], "Принято, ед.", allowed={"Горловка"})
    assert [r["value"] for r in limited] == ["Горловка"]


async def test_ladder_refuses_until_levels_are_confirmed(client, admin_headers, seed_dataset):
    """Неподтверждённую иерархию не применяем: система не угадывает молча."""
    d = (await client.post("/dashboards", json={"name": "ztest_ladder"},
                           headers=admin_headers)).json()
    p = (await client.post(f"/dashboards/{d['id']}/pages", json={"name": "Обзор"},
                           headers=admin_headers)).json()
    await client.post(f"/dashboard-pages/{p['id']}/widgets", headers=admin_headers,
                      json={"name": "таблица", "widget_type": "table",
                            "config": {"dataset_code": "t_ds", "value_fields": ["plan", "fact"]}})
    r = await client.get(f"/dashboard-pages/{p['id']}/ladder", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is False
    assert "подтвер" in body["reason"].lower()

    # Страница без датасетных виджетов — тоже честный отказ, а не ошибка.
    p2 = (await client.post(f"/dashboards/{d['id']}/pages", json={"name": "Текст"},
                            headers=admin_headers)).json()
    await client.post(f"/dashboard-pages/{p2['id']}/widgets", headers=admin_headers,
                      json={"name": "заголовок", "widget_type": "text", "config": {"heading": "Привет"}})
    body2 = (await client.get(f"/dashboard-pages/{p2['id']}/ladder", headers=admin_headers)).json()
    assert body2["available"] is False

    from tests.conftest import purge_dashboard
    await purge_dashboard(d["id"])


@pytest.fixture
async def tree(ids):
    """Иерархическая форма: «ведомство · услуга · мера» плюс свод.

    Нужна отдельно от `seed_dataset`: у того графы зовутся «plan»/«fact», в
    именах нет разделителя, и ветка для такой формы бессмысленна по существу —
    фильтр к ней не применяется вовсе (что тест ниже заодно и подтверждает).
    """
    fields = {
        "zld_rr_reg": ("Росреестр · Государственная регистрация прав · Принято, ед.", 441.0),
        "zld_rr_kad": ("Росреестр · Государственный кадастровый учет · Принято, ед.", 244.0),
        "zld_mvd": ("МВД · Регистрационный учет · Принято, ед.", 448.0),
        "zld_itogo": ("ИТОГО · Принято, ед.", 5426.0),
    }
    async with db.acquire() as conn:
        await conn.execute("delete from objects where name='zld_obj' and organization_id=$1", ids["org"])
        obj = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'zld_obj') returning id", ids["org"])
        rel = await conn.fetchval(
            "insert into dataset_releases(organization_id,code,name,status,"
            "reporting_period_start,created_by,object_id) "
            "values($1,'zld_ds','Дерево','released','2026-04-01',$2,$3) returning id",
            ids["org"], ids["admin"], obj)
        for code, (name, val) in fields.items():
            await conn.execute(
                "insert into canonical_fields(object_id,code,name,data_type) values($1,$2,$3,'number')",
                obj, code, name)
            # 🔴 Объявление графы в выпуске обязательно: имена граф виджеты
            # читают отсюда (`_field_titles`), а не из canonical_fields. Без
            # этой строки фильтр по ветке молча не находил разделителя и не
            # применялся вовсе — фикстура заводит значения в обход конвейера.
            await conn.execute(
                "insert into dataset_release_fields(dataset_release_id,canonical_field_code) "
                "values($1,$2)", rel, code)
            for i, row in enumerate(["Отд. 1", "Отд. 2"]):
                await conn.execute(
                    "insert into dataset_values(dataset_release_id,row_index,row_label,"
                    "canonical_field_code,value_number) values($1,$2,$3,$4,$5)",
                    rel, i, row, code, val / 2)
        await conn.execute(
            "insert into object_layout_templates(object_id,fingerprint,dataset_code,levels) "
            "values($1,'zld-fp','zld_ds',$2::jsonb)", obj,
            '{"fingerprint":"zld-fp","levels":[{"index":0,"name":"Ведомство"},'
            '{"index":1,"name":"Услуга"}],"row_level":"Отделение","group_lone":true,'
            '"measure_default":"Принято, ед."}')
    yield {"code": "zld_ds", "object_id": obj}
    async with db.acquire() as conn:
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where code='zld_ds')")
        await conn.execute("delete from dataset_releases where code='zld_ds'")
        await conn.execute("delete from objects where name='zld_obj' and organization_id=$1", ids["org"])


async def test_branch_is_part_of_the_cache_key(client, admin_headers, tree):
    """🔴 Ветка входит в ключ кэша.

    Без неё второй запрос по ветке получил бы ответ, посчитанный для корня, —
    из кэша и потому совершенно незаметно.
    """
    d = (await client.post("/dashboards", json={"name": "ztest_ladder_cache"},
                           headers=admin_headers)).json()
    p = (await client.post(f"/dashboards/{d['id']}/pages", json={"name": "Обзор"},
                           headers=admin_headers)).json()
    w = (await client.post(f"/dashboard-pages/{p['id']}/widgets", headers=admin_headers,
                           json={"name": "карточка", "widget_type": "kpi",
                                 "config": {"dataset_code": "zld_ds", "value_field": "zld_rr_reg"}})).json()

    async with db.acquire() as conn:
        org = await conn.fetchval("select id from organizations order by created_at limit 1")
        uid = await conn.fetchval("select id from users where login='admin'")
        user = {"id": uid, "organization_id": org}
        from app.modules.dashboards._widgetdata import compute_widget_data
        root = await compute_widget_data(conn, org, w["id"], user=user)
        mine = await compute_widget_data(conn, org, w["id"], user=user, level_path=["Росреестр"])
        alien = await compute_widget_data(conn, org, w["id"], user=user, level_path=["МВД"])
    assert root.get("value") == 441
    assert mine.get("value") == 441, "своя ветка считается"
    assert alien.get("not_in_branch") is True, "чужая ветка не берётся из кэша корня"

    from tests.conftest import purge_dashboard
    await purge_dashboard(d["id"])


async def test_ladder_walks_the_tree(client, admin_headers, tree):
    """Полный проход: корень → ведомство → услуга → отделения."""
    d = (await client.post("/dashboards", json={"name": "ztest_ladder_walk"},
                           headers=admin_headers)).json()
    p = (await client.post(f"/dashboards/{d['id']}/pages", json={"name": "Обзор"},
                           headers=admin_headers)).json()
    await client.post(f"/dashboard-pages/{p['id']}/widgets", headers=admin_headers,
                      json={"name": "таблица", "widget_type": "table",
                            "config": {"dataset_code": "zld_ds",
                                       "value_fields": ["zld_rr_reg", "zld_mvd"]}})
    url = f"/dashboard-pages/{p['id']}/ladder"

    root = (await client.get(url, headers=admin_headers)).json()
    assert root["available"] is True
    assert root["level_name"] == "Ведомство"
    assert root["measure"] == "Принято, ед."
    by = {c["value"]: c["total"] for c in root["children"]}
    assert by == {"Росреестр": 685, "МВД": 448}, "свод в ступень не попадает"

    step = (await client.get(url, headers=admin_headers,
                             params={"level": ["Росреестр"]})).json()
    assert step["level_name"] == "Услуга" and step["is_rows"] is False
    assert {c["value"] for c in step["children"]} == {
        "Государственная регистрация прав", "Государственный кадастровый учет"}

    leaf = (await client.get(url, headers=admin_headers, params={
        "level": ["Росреестр", "Государственный кадастровый учет"]})).json()
    assert leaf["is_rows"] is True and leaf["level_name"] == "Отделение"
    assert {c["value"] for c in leaf["children"]} == {"Отд. 1", "Отд. 2"}

    # Ступень пропущена — говорим об этом словами, а имя уровня не склоняем.
    skipped = (await client.get(url, headers=admin_headers, params={"level": ["МВД"]})).json()
    assert skipped["is_rows"] is False or "Услуга" in (skipped.get("note") or "")

    from tests.conftest import purge_dashboard
    await purge_dashboard(d["id"])
