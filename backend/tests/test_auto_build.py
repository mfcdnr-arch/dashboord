"""Авто-сборка дашборда по объекту.

Главное правило: сколько числовых показателей человек увидел в предпросмотре
разметки, столько карточек он должен получить и на собранном дашборде. Раньше
брались только первые ДВА поля — на госформе из 14 граф это выглядело как
потеря данных (замечание заказчика 11.08.2026).
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db  # noqa: E402
from conftest import purge_dashboard  # noqa: E402

# Имена как в госформе: «Показатель · Роль · Разрез». По ним система и решает,
# что показать числом, что трендом и где есть пара «план + факт».
FIELDS = [
    ("f1", "Обращения · Факт · нарастающим итогом"),
    ("f2", "Обращения · Факт · за отчетную неделю"),
    ("f3", "Доставленные · План (до 1 сентября 2026 г.)"),
    ("f4", "Доставленные · Факт · нарастающим итогом"),
    ("f5", "Доставленные · Факт · за отчетную неделю"),
    ("f6", "Записались · Факт · нарастающим итогом"),
]
WEEKLY = {"f2", "f5"}   # их система показывает и числом, и трендом


async def _seed_fields(org_id):
    """seed_dataset вставляет значения в обход конвейера распознавания и НЕ
    заводит метаданные полей — а авто-сборка берёт показатели именно из них."""
    async with db.acquire() as conn:
        rel = await conn.fetchrow(
            "select id, object_id from dataset_releases where organization_id=$1 and code='t_ds' "
            "and status<>'superseded' order by reporting_period_start desc limit 1", org_id)
        for code, name in FIELDS:
            await conn.execute(
                "insert into canonical_fields(object_id,code,name,data_type) values($1,$2,$3,'number') "
                "on conflict (object_id,code) do nothing", rel["object_id"], code, name)
            await conn.execute(
                "insert into dataset_release_fields(dataset_release_id,canonical_field_code) values($1,$2) "
                "on conflict do nothing", rel["id"], code)
    return rel


async def _dataset_code(org_id) -> str:
    async with db.acquire() as conn:
        return await conn.fetchval(
            "select code from dataset_releases where organization_id=$1 and code='t_ds' limit 1", org_id)


async def _cleanup_fields(rel):
    async with db.acquire() as conn:
        codes = [c for c, _ in FIELDS]
        await conn.execute(
            "delete from dataset_release_fields where dataset_release_id=$1 and canonical_field_code=any($2::text[])",
            rel["id"], codes)
        await conn.execute(
            "delete from canonical_fields where object_id=$1 and code=any($2::text[])", rel["object_id"], codes)


async def test_auto_build_makes_kpi_for_every_numeric_field(client, admin_headers, seed_dataset, ids):
    rel = await _seed_fields(ids["org"])
    did = None
    try:
        r = await client.post("/dashboards/auto", headers=admin_headers,
                              json={"object_id": str(rel["object_id"]), "name": "ztest_auto"})
        assert r.status_code in (200, 201), r.text
        did = r.json()["dashboard_id"]

        async with db.acquire() as conn:
            rows = await conn.fetch(
                "select widget_type, name, config, position_x, position_y, width "
                "from widgets where dashboard_id=$1::uuid order by position_y, position_x", did)

        import json

        def cfg_of(w):
            return json.loads(w["config"]) if isinstance(w["config"], str) else w["config"]

        # Разрезы одного показателя идут ОДНОЙ карточкой (kpi_group), одиночные —
        # обычной. Проверяем не число карточек, а покрытие: ни один показатель
        # не должен потеряться при группировке.
        cards = [w for w in rows if w["widget_type"] in ("kpi", "kpi_group")]
        used = []
        for w in cards:
            c = cfg_of(w)
            used += c.get("value_fields") or ([c["value_field"]] if c.get("value_field") else [])
        assert sorted(used) == sorted(c for c, _ in FIELDS), \
            f"каждый показатель должен быть показан ровно один раз: {sorted(used)}"
        groups = [w for w in rows if w["widget_type"] == "kpi_group"]
        assert groups, "у показателя с несколькими разрезами должна быть группа"
        assert all(len(cfg_of(w)["value_fields"]) > 1 for w in groups), \
            "в группу попадают только показатели с несколькими разрезами"

        # По ТРИ карточки в ряд (ширина 4): на четверти ширины длинные имена
        # госформ обрезались до «Количестı отправ…», и карточка переставала
        # отвечать на вопрос, что за число она показывает. 3 × 4 = 12 колонок
        # заполняются без дыр.
        assert {w["position_x"] for w in cards} <= {0, 4, 8}
        assert all(w["width"] == 4 for w in cards)

        types = [w["widget_type"] for w in rows]
        assert "table" in types, "таблица-первичка обязательна"
        assert "bar" in types, "график по строкам обязателен"
        assert "compare" in types, "нужен общий график: 6 карточек не показывают соотношение"
    finally:
        if did:
            await purge_dashboard(did)
        await _cleanup_fields(rel)


async def test_view_is_chosen_by_role_of_the_indicator(client, admin_headers, seed_dataset, ids):
    """Состав виджетов подбирается по смыслу показателей, а не одинаково.

    Тренд получает КАЖДЫЙ показатель, по которому он возможен (есть несколько
    отчётных периодов): «сколько сейчас» и «куда идёт» — разные вопросы, и
    второй задают не только по недельному срезу. Пара «План + Факт» одного
    показателя даёт полосу выполнения вместо двух карточек, из которых процент
    считают в уме.
    """
    rel = await _seed_fields(ids["org"])
    did = None
    try:
        r = await client.post("/dashboards/auto", headers=admin_headers,
                              json={"object_id": str(rel["object_id"]), "name": "ztest_auto_dyn"})
        did = r.json()["dashboard_id"]
        async with db.acquire() as conn:
            rows = await conn.fetch(
                "select widget_type, config from widgets where dashboard_id=$1::uuid", did)
        import json
        def fields_of(kind):
            out = []
            for w in rows:
                if w["widget_type"] != kind:
                    continue
                cfg = json.loads(w["config"]) if isinstance(w["config"], str) else w["config"]
                out.append(cfg.get("value_field"))
            return sorted(f for f in out if f)

        # Тренды рядом с матрицей ограничены главными показателями: матрица уже
        # показывает движение ВСЕХ по всем датам, и полтора десятка почти
        # одинаковых графиков превращали страницу в ленту. Сами показатели при
        # этом не теряются — они строки матрицы.
        dyn = fields_of("dynamics")
        assert 0 < len(dyn) <= 4, f"трендов должно остаться немного: {dyn}"
        assert set(dyn) <= {c for c, _ in FIELDS}
        matrix = [w for w in rows if w["widget_type"] == "matrix"]
        assert matrix, "движение остальных показателей обязана показывать матрица"
        # Карточка нужна каждому показателю, но разрезы одного показателя идут
        # одной группой — считаем покрытие, а не число карточек.
        import json as _json
        covered = sorted(fields_of("kpi") + [
            f for w in rows if w["widget_type"] == "kpi_group"
            for f in (_json.loads(w["config"]) if isinstance(w["config"], str) else w["config"])["value_fields"]])
        assert covered == sorted(c for c, _ in FIELDS), f"показатель потерялся: {covered}"
        assert any(w["widget_type"] == "plan_fact" for w in rows), \
            "у «Доставленные» есть и План, и Факт — должна быть полоса выполнения"
    finally:
        if did:
            await purge_dashboard(did)
        await _cleanup_fields(rel)


async def test_auto_build_widgets_do_not_overlap(client, admin_headers, seed_dataset, ids):
    """Виджеты не должны накладываться друг на друга: раскладка считается
    вручную, и смещение рядов легко сломать при правке."""
    rel = await _seed_fields(ids["org"])
    did = None
    try:
        r = await client.post("/dashboards/auto", headers=admin_headers,
                              json={"object_id": str(rel["object_id"]), "name": "ztest_auto_grid"})
        did = r.json()["dashboard_id"]
        async with db.acquire() as conn:
            rows = await conn.fetch(
                "select page_id, name, position_x x, position_y y, width w, height h "
                "from widgets where dashboard_id=$1::uuid", did)
        # Координаты повторяются на РАЗНЫХ страницах — это норма, поэтому
        # пересечения ищем внутри каждой страницы отдельно.
        by_page: dict = {}
        for w in rows:
            by_page.setdefault(str(w["page_id"]), []).append(
                (w["x"], w["y"], w["x"] + w["w"], w["y"] + w["h"], w["name"]))
        assert len(by_page) > 1, "страницы должны быть разделены по смыслу"
        for boxes in by_page.values():
            for i, a in enumerate(boxes):
                for b in boxes[i + 1:]:
                    overlap = not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])
                    assert not overlap, f"пересекаются «{a[4]}» и «{b[4]}»"
                assert a[2] <= 12, f"«{a[4]}» выходит за 12 колонок"
    finally:
        if did:
            await purge_dashboard(did)
        await _cleanup_fields(rel)


async def test_plan_matches_what_gets_built(client, admin_headers, seed_dataset, ids):
    """«Будет создано N виджетов» обязано совпасть с тем, что создалось.

    План и сборка идут через ОДИН планировщик — тест защищает именно это
    свойство: разойдясь, они превратили бы предпросмотр в обман.
    """
    rel = await _seed_fields(ids["org"])
    did = None
    try:
        body = {"object_id": str(rel["object_id"]), "name": "ztest_plan"}
        plan = (await client.post("/dashboards/auto/plan", headers=admin_headers, json=body)).json()
        assert plan["widgets"] > 0
        assert plan["object"]["id"] == str(rel["object_id"])

        r = await client.post("/dashboards/auto", headers=admin_headers, json=body)
        did = r.json()["dashboard_id"]
        assert r.json()["widgets"] == plan["widgets"], "план разошёлся со сборкой"
        async with db.acquire() as conn:
            real = await conn.fetchval(
                "select count(*) from widgets where dashboard_id=$1::uuid", did)
        assert real == plan["widgets"]
    finally:
        if did:
            await purge_dashboard(did)
        await _cleanup_fields(rel)


async def test_selection_narrows_the_build(client, admin_headers, seed_dataset, ids):
    """Снятые галочки уменьшают сборку: два показателя и только карточки."""
    rel = await _seed_fields(ids["org"])
    did = None
    try:
        code = await _dataset_code(ids["org"])
        body = {
            "object_id": str(rel["object_id"]), "name": "ztest_sel",
            "selection": {code: {"fields": ["f1", "f2"], "blocks": ["kpi"]}},
        }
        plan = (await client.post("/dashboards/auto/plan", headers=admin_headers, json=body)).json()
        assert plan["widgets"] == 1, f"два разреза одного показателя — одна карточка, план говорит {plan['widgets']}"

        did = (await client.post("/dashboards/auto", headers=admin_headers, json=body)).json()["dashboard_id"]
        async with db.acquire() as conn:
            types = await conn.fetch(
                "select widget_type from widgets where dashboard_id=$1::uuid", did)
        # f1 и f2 — разрезы ОДНОГО показателя («Обращения»), поэтому карточка
        # одна: группа с двумя строками.
        assert [t["widget_type"] for t in types] == ["kpi_group"]
    finally:
        if did:
            await purge_dashboard(did)
        await _cleanup_fields(rel)


async def test_rebuild_replaces_content_and_keeps_dashboard(client, admin_headers, seed_dataset, ids):
    """Пересборка меняет наполнение, но не плодит дашборды и не теряет сам
    дашборд: на нём висят права доступа, обсуждение и история."""
    rel = await _seed_fields(ids["org"])
    did = None
    try:
        body = {"object_id": str(rel["object_id"]), "name": "ztest_rebuild"}
        did = (await client.post("/dashboards/auto", headers=admin_headers, json=body)).json()["dashboard_id"]
        async with db.acquire() as conn:
            before = await conn.fetchval("select count(*) from widgets where dashboard_id=$1::uuid", did)

        code = await _dataset_code(ids["org"])
        r = await client.post("/dashboards/auto", headers=admin_headers, json={
            **body, "dashboard_id": did,
            "selection": {code: {"fields": ["f1"], "blocks": ["kpi"]}},
        })
        assert r.status_code in (200, 201), r.text
        assert r.json()["dashboard_id"] == did, "пересборка не должна создавать новый дашборд"
        async with db.acquire() as conn:
            after = await conn.fetch(
                "select widget_type from widgets where dashboard_id=$1::uuid", did)
            pages = await conn.fetchval(
                "select count(*) from dashboard_pages where dashboard_id=$1::uuid", did)
        assert before > 1 and [w["widget_type"] for w in after] == ["kpi"], "старое наполнение должно уйти"
        assert pages == 1, "страница ровно одна — старые не копятся"
    finally:
        if did:
            await purge_dashboard(did)
        await _cleanup_fields(rel)


def test_form_title_strips_trailing_report_date():
    """Заголовок виджета называет ФОРМУ, а не отчётную дату.

    Имя виджета фиксируется в момент сборки и больше не меняется, а данные
    обновляются — поэтому любая дата в заголовке рано или поздно устаревает.
    Живая дата у виджета своя: строка «🕓 данные на …» под ним.
    """
    from app.modules.dashboards._suggest import form_title

    assert form_title("Показатели MAX 22.07.2026") == "Показатели MAX"
    assert form_title("Показатели MAX 2026-07-22") == "Показатели MAX"
    assert form_title("Форма №2 (01.04.2026)") == "Форма №2"
    assert form_title("Сводка 15.04.26") == "Сводка"
    # Год внутри имени — часть названия формы, а не отчётная дата.
    assert form_title("Отчёт за 2026 год") == "Отчёт за 2026 год"
    assert form_title("Внедрение сервиса МАХ") == "Внедрение сервиса МАХ"
    # Пустой результат не отдаём: лучше имя с датой, чем виджет без имени.
    assert form_title("22.07.2026") == "22.07.2026"


async def test_dataset_name_taken_from_latest_release(client, admin_headers, seed_dataset):
    """🔴 Имя набора бралось как max(name) — АЛФАВИТНЫЙ максимум по названиям
    выпусков. У формы, названной с датой, это давало не последний отчёт:
    «29.06.2026» «больше» строки «22.07.2026» посимвольно.
    """
    from app import db
    from app.modules.dashboards._suggest import _dataset_display_name

    async with db.acquire() as conn:
        org = await conn.fetchval(
            "select organization_id from dataset_releases where code=$1 limit 1", seed_dataset["code"])
        # Старое имя у ПОЗДНЕГО отчёта, «алфавитно большее» — у раннего.
        await conn.execute(
            "update dataset_releases set name='Показатели MAX 22.07.2026' "
            "where code=$1 and reporting_period_start='2026-02-01'", seed_dataset["code"])
        await conn.execute(
            "update dataset_releases set name='Показатели MAX 29.06.2026' "
            "where code=$1 and reporting_period_start='2026-01-01'", seed_dataset["code"])
        try:
            name = await _dataset_display_name(conn, org, seed_dataset["code"])
        finally:
            await conn.execute(
                "update dataset_releases set name='Тест ДС' where code=$1", seed_dataset["code"])
    # Имя берётся у последнего отчёта, и дата из него убрана.
    assert name == "Показатели MAX", name
