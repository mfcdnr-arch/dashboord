"""Группа разрезов одной карточкой и предупреждение о разных разрезах план/факта.

В госформе у показателя обычно три столбца («нарастающим итогом», «… текущий
месяц», «за отчётную неделю»). Раньше каждый занимал свою карточку: тринадцать
карточек «Обзора» оказывались четырьмя показателями, а экран — стеной
одинаковых заголовков.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from conftest import db, purge_dashboard  # noqa: E402


async def _fields(ids, pairs):
    """Справочник полей объекта t_obj с человеческими именами госформы."""
    async with db.acquire() as conn:
        obj = await conn.fetchval("select id from objects where name='t_obj'")
        for code, name in pairs:
            await conn.execute(
                "insert into canonical_fields(object_id,code,name,data_type) "
                "values($1,$2,$3,'number') on conflict do nothing", obj, code, name)
        return obj


async def _cleanup(obj, codes):
    async with db.acquire() as conn:
        await conn.execute("delete from canonical_fields where object_id=$1 and code=any($2::text[])",
                           obj, list(codes))


async def test_group_shows_every_slice_with_its_own_change(client, admin_headers, seed_dataset, ids):
    """Карточка группы: строка на разрез, у каждой своё значение и свой прирост."""
    obj = await _fields(ids, [("plan", "Обращения · Факт · нарастающим итогом"),
                              ("fact", "Обращения · Факт · за отчетную неделю")])
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_group"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "О"})).json()["id"]
        r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                              json={"name": "Обращения", "widget_type": "kpi_group",
                                    "config": {"dataset_code": "t_ds", "value_fields": ["plan", "fact"],
                                               "compare_prev": True}})
        assert r.status_code == 201, r.text
        d = (await client.get(f"/widgets/{r.json()['id']}/data", headers=admin_headers)).json()
        assert d["type"] == "kpi_group"
        by = {x["field"]: x for x in d["lines"]}
        assert by["plan"]["value"] == 180.0 and by["fact"]["value"] == 173.0
        # Подпись строки — РАЗРЕЗ, а не полное имя: показатель назван в заголовке.
        assert by["plan"]["label"] == "нарастающим итогом"
        assert by["fact"]["label"] == "за отчетную неделю"
        # Прирост считается по каждому разрезу ОТДЕЛЬНО, а не один на карточку.
        assert by["plan"]["delta"] == 15.0
        assert by["plan"]["prev_period"] == "2026-01-01"
        # У `fact` в прошлом выпуске данных не было: процент от нуля не
        # считается (то же правило, что у обычной карточки).
        assert by["fact"]["delta_pct"] is None
        assert d["subject"] == "Обращения"
    finally:
        await purge_dashboard(did)
        await _cleanup(obj, ["plan", "fact"])


async def test_plan_fact_warns_when_slices_differ(client, admin_headers, seed_dataset, ids):
    """«Выполнение 656 %» бывает верным арифметически и бессмысленным по сути:
    план за неделю против накопительного факта. Система обязана сказать об этом."""
    obj = await _fields(ids, [("plan", "Обращения · План · за отчетную неделю"),
                              ("fact", "Обращения · Факт · нарастающим итогом")])
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_slice"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "О"})).json()["id"]
        r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                              json={"name": "план и факт", "widget_type": "plan_fact",
                                    "config": {"dataset_code": "t_ds", "plan_field": "plan", "fact_field": "fact"}})
        d = (await client.get(f"/widgets/{r.json()['id']}/data", headers=admin_headers)).json()
        assert d["slice_note"], "разные разрезы плана и факта должны быть названы"
        assert "неделю" in d["slice_note"] and "нарастающим" in d["slice_note"]

        # План «до 1 сентября» против накопительного факта — НОРМА, и
        # предупреждать здесь было бы шумом: план так и задаётся, на срок.
        async with db.acquire() as conn:
            await conn.execute("update canonical_fields set name='Обращения · План (до 1 сентября 2026 г.)' "
                               "where object_id=$1 and code='plan'", obj)
        d2 = (await client.get(f"/widgets/{r.json()['id']}/data", headers=admin_headers)).json()
        assert d2["slice_note"] is None
    finally:
        await purge_dashboard(did)
        await _cleanup(obj, ["plan", "fact"])


async def test_summary_answers_how_things_are(client, admin_headers, seed_dataset, ids):
    """Строка «как дела»: сколько показателей выросло и просело к прошлому отчёту."""
    obj = await _fields(ids, [("plan", "Обращения · Факт · нарастающим итогом"),
                              ("fact", "Обращения · Факт · за отчетную неделю")])
    did = (await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_sum"})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "О"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "Обращения", "widget_type": "kpi",
                                "config": {"dataset_code": "t_ds", "value_field": "plan"}})
        s = (await client.get(f"/dashboard-pages/{pid}/summary", headers=admin_headers)).json()
        # plan: 165 → 180 между двумя выпусками фикстуры.
        assert s["period"] == "2026-02-01" and s["prev_period"] == "2026-01-01"
        assert s["grew"] == 1 and s["fell"] == 0
        assert s["top"] and s["top"][0]["delta"] == 15.0
        # Показатель назван предметом, без разреза: в строке важно «что», а не «как».
        assert s["top"][0]["name"] == "Обращения"

        # Страница без датасетных виджетов — пустое резюме, а не ошибка.
        pid2 = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "Т"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid2}/widgets", headers=admin_headers,
                          json={"name": "текст", "widget_type": "text", "config": {"heading": "Привет"}})
        s2 = (await client.get(f"/dashboard-pages/{pid2}/summary", headers=admin_headers)).json()
        assert s2["grew"] == 0 and s2["top"] == []
    finally:
        await purge_dashboard(did)
        await _cleanup(obj, ["plan", "fact"])

def test_plan_is_not_a_slice_of_the_fact():
    """🔴 План не кладётся в группу разрезов — он цель, а не разрез.

    Найдено предпросмотром пересборки дашборда заказчика: группа «записавшихся»
    открывалась строкой «(до 1 сентября 2026 г.) 41 971» над «нарастающим итогом
    275 694». Обе цифры верны, но рядом друг с другом план читается как ещё одно
    фактическое число — разницы между целью и фактом не видно.

    План при этом НЕ пропадает: на той же странице его показывают полоса
    «план-факт» и термометр.
    """
    from app.modules.dashboards import _suggest

    fields = [
        {"code": "plan", "name": "Записались · План (до 1 сентября 2026 г.)"},
        {"code": "fact", "name": "Записались · Факт · нарастающим итогом"},
        {"code": "week", "name": "Записались · Факт · за отчетную неделю"},
    ]
    ds = [{"code": "t", "name": "Форма", "periods": 4, "releases": 4, "rows": 1,
           "fields": fields, "period_dates": ["2026-08-%02d" % d for d in (5, 12, 19, 26)]}]
    specs = _suggest.plan_auto_build(ds, None)

    group = next(s for s in specs if s["widget_type"] == "kpi_group")
    assert "plan" not in group["config"]["value_fields"], "план не разрез"
    assert set(group["config"]["value_fields"]) == {"fact", "week"}

    # И план всё равно показан — парой «план-факт».
    assert any(s["widget_type"] in ("plan_fact", "bullet") for s in specs)


def test_plan_without_a_fact_does_not_vanish():
    """А план, которому не с чем встать в пару, остаётся отдельной карточкой.

    Иначе он пропал бы с дашборда молча: полосы и термометр его не покажут —
    им нужен факт.
    """
    from app.modules.dashboards import _suggest

    fields = [
        {"code": "plan", "name": "Охват · План (до 1 сентября 2026 г.)"},
        {"code": "other", "name": "Обращения · Факт · нарастающим итогом"},
    ]
    ds = [{"code": "t", "name": "Форма", "periods": 4, "releases": 4, "rows": 1,
           "fields": fields, "period_dates": ["2026-08-%02d" % d for d in (5, 12, 19, 26)]}]
    specs = _suggest.plan_auto_build(ds, None)

    kpi_fields = {s["config"].get("value_field") for s in specs if s["widget_type"] == "kpi"}
    assert "plan" in kpi_fields, "непарный план обязан остаться на виду"

