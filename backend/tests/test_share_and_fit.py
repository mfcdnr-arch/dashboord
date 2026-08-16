"""Два дефекта, замеченные заказчиком на его дашборде.

(1) **Проценты складывались.** Карточка сворачивает строки датасета в одно
    число суммой — для количеств верно, для долей бессмыслица: «12,4 % + 9,8 %
    + 31,0 %» = 53,2 % выглядит как показатель, но не значит ничего. Такие
    столбцы теперь усредняются, и карточка честно подписывает «среднее по N
    строкам» — среднее по строкам тоже приближение, выдавать его за точный
    итог нельзя.

(2) **Старые дашборды держат карточки 3×3.** Собранные до перехода авто-сборки
    на крупные карточки, они обрезают имя показателя до «Колич обращ за…» и не
    вмещают само число. Кнопка «Подогнать размеры» применяет ту же раскладку,
    что и авто-сборка, НЕ трогая состав страницы.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.dashboards import _suggest
from app.modules.dashboards._aggregate import aggregate_series, is_share


def test_share_columns_are_recognised_by_name():
    """Долю от количества отличаем по имени столбца — единицы там и живут."""
    assert is_share("Доля доставленных, %")
    assert is_share("Удельный вес отказов")
    assert is_share("Количество услуг", unit="%"), "явная единица виджета тоже считается"
    assert not is_share("Количество обращений за результатом оказания услуг")
    assert not is_share(None, None)


def test_percent_column_is_averaged_not_summed():
    """Ключевое: проценты по строкам усредняются, количества складываются."""
    value, how = aggregate_series([12.4, 9.8, 31.0], "Доля доставленных, %")
    assert how == "avg" and round(value, 2) == 17.73

    value, how = aggregate_series([100, 50, 30], "Количество обращений")
    assert how == "sum" and value == 180

    assert aggregate_series([], "Доля, %") == (0.0, "sum"), "пустой столбец не должен падать"


async def test_kpi_on_percent_column_shows_average(client, admin_headers, ids):
    """Сквозь весь расчёт: карточка по процентной графе даёт среднее и говорит об этом."""
    org = ids["org"]
    async with db.acquire() as conn:
        # Хвост прерванного прогона: без этого второй запуск падает на unique.
        await conn.execute(
            "delete from dataset_values where dataset_release_id in "
            "(select id from dataset_releases where code='ztest_share')")
        await conn.execute("delete from dataset_releases where code='ztest_share'")
        await conn.execute(
            "delete from canonical_fields where object_id in "
            "(select id from objects where name='ztest_share_obj')")
        await conn.execute("delete from objects where name='ztest_share_obj'")
        obj = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_share_obj') returning id", org)
        await conn.execute(
            "insert into canonical_fields(object_id,code,name,data_type) "
            "values($1,'share_pct','Доля доставленных, %','number')", obj)
        rel = await conn.fetchval(
            "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,created_by,object_id) "
            "values($1,'ztest_share','Доли',$2,'2026-03-01',$3,$4) returning id",
            org, "released", ids["admin"], obj)
        for i, (lbl, v) in enumerate((("Донецк", 12.4), ("Макеевка", 9.8), ("Горловка", 31.0))):
            await conn.execute(
                "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
                "values($1,$2,$3,'share_pct',$4)", rel, i, lbl, v)

    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_share_dash"})
    did = r.json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                             json={"name": "Стр"})).json()["id"]
    try:
        r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "ztest доля", "widget_type": "kpi",
            "config": {"dataset_code": "ztest_share", "value_field": "share_pct"}})
        data = (await client.get(f"/widgets/{r.json()['id']}/data", headers=admin_headers)).json()
        assert round(data["value"], 2) == 17.73, "сумма 53,2 % была бы бессмыслицей"
        assert data["aggregate"] == "avg" and data["rows_used"] == 3, \
            "приближение нельзя выдавать за точный итог — карточка это подписывает"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)
            await conn.execute("delete from dataset_values where dataset_release_id=$1", rel)
            await conn.execute("delete from dataset_releases where id=$1", rel)
            await conn.execute("delete from canonical_fields where object_id=$1", obj)
            await conn.execute("delete from objects where id=$1", obj)


def test_percent_column_gets_a_gauge_in_auto_build():
    """Процентная ГРАФА формы — спидометр: доля читается на шкале.

    Раньше этого не делали, потому что карточка складывала проценты и шкала
    показала бы бессмыслицу; теперь такие столбцы усредняются.
    """
    ds = [{"code": "t", "name": "Форма", "periods": 1, "releases": 1, "period_dates": [],
           "fields": [{"code": "cnt", "name": "Количество обращений"},
                      {"code": "share", "name": "Доля доставленных, %"}]}]
    specs = _suggest.plan_auto_build(ds, None)
    # Только «Обзор»: на «Первичных данных» по тому же полю строится график
    # по строкам, и он затирал бы карточку в этом разборе.
    by_field = {s["config"].get("value_field"): s for s in specs
                if s["config"].get("value_field") and s["page"] == _suggest.PAGE_OVERVIEW}
    assert by_field["share"]["widget_type"] == "gauge"
    assert by_field["share"]["config"]["unit"] == "%"
    assert by_field["cnt"]["widget_type"] == "kpi", "количество остаётся карточкой"


def test_fit_layout_enlarges_old_cards_without_overlap():
    """Раскладка «подогнать размеры»: карточки крупнее, наложений нет."""
    widgets = [{"id": f"w{i}", "widget_type": t} for i, t in enumerate(
        ["kpi", "kpi", "kpi", "kpi", "gauge", "dynamics", "table"])]
    out = _suggest.fit_layout(widgets)

    assert [o["id"] for o in out] == [w["id"] for w in widgets], "порядок виджетов сохраняется"
    kpi = next(o for o in out if o["id"] == "w0")
    assert (kpi["width"], kpi["height"]) == (4, 5), "карточка 3×3 обрезала имя показателя"
    assert next(o for o in out if o["id"] == "w6")["width"] == 12, "таблица — во всю ширину"

    for i, a in enumerate(out):
        assert a["position_x"] + a["width"] <= 12, a
        for b in out[i + 1:]:
            overlap = (a["position_x"] < b["position_x"] + b["width"]
                       and b["position_x"] < a["position_x"] + a["width"]
                       and a["position_y"] < b["position_y"] + b["height"]
                       and b["position_y"] < a["position_y"] + a["height"])
            assert not overlap, (a, b)


async def test_fit_layout_endpoint_keeps_the_page_intact(client, admin_headers, seed_dataset):
    """Кнопка меняет размеры, но не состав: ни один виджет не пропадает."""
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_fit_dash"})
    did = r.json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                             json={"name": "Обзор"})).json()["id"]
    try:
        made = []
        for i in range(4):
            r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
                "name": f"ztest карточка {i}", "widget_type": "kpi",
                "width": 3, "height": 3, "position_x": (i % 4) * 3, "position_y": 0,
                "config": {"dataset_code": seed_dataset["code"], "value_field": "plan"}})
            made.append(r.json()["id"])

        r = await client.post(f"/dashboard-pages/{pid}/fit-layout", headers=admin_headers)
        assert r.status_code == 200, r.text
        assert r.json() == {"widgets": 4, "changed": 4}

        rows = (await client.get(f"/dashboard-pages/{pid}/widgets", headers=admin_headers)).json()["widgets"]
        assert {w["id"] for w in rows} == set(made), "состав страницы меняться не должен"
        assert all((w["width"], w["height"]) == (4, 5) for w in rows)
        # Три в ряд: четвёртая карточка уходит на следующую строку, а не за край.
        assert sorted((w["position_x"], w["position_y"]) for w in rows) == [(0, 0), (0, 5), (4, 0), (8, 0)]

        # Повторный вызов ничего не меняет — операция идемпотентна.
        assert (await client.post(f"/dashboard-pages/{pid}/fit-layout",
                                  headers=admin_headers)).json()["changed"] == 0
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_fit_layout_needs_rights(client, viewer, admin_headers):
    """Раскладку правит тот, кто управляет дашбордами, а не любой зритель."""
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_fit_acl"})
    did = r.json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                             json={"name": "Стр"})).json()["id"]
    try:
        assert (await client.post(f"/dashboard-pages/{pid}/fit-layout",
                                  headers=viewer["headers"])).status_code == 403
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)
