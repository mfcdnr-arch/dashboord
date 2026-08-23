"""Мастер, этап 3: отдельные страницы по отчётным периодам.

Заказчику нужны ОБА варианта: сводный дашборд, который обновляется сам, и
страницы за конкретные недели. Разница принципиальная и легко теряется:
у сводной страницы виджет читает ПОСЛЕДНИЙ выпуск, у страницы-среза — выпуск
за закреплённую дату, и приход новой недели её не меняет. Здесь проверяется
именно это, а не только наличие страниц.
"""


import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.dashboards import _suggest
from tests.conftest import purge_dashboard


def _numbers(obj) -> set:
    """Все числа ответа — рекурсивно, без строк.

    Нужен, чтобы проверять ЗНАЧЕНИЯ, а не текст JSON: в ответе есть
    идентификаторы, даты и имена, и поиск подстрокой в них случайно находит
    что угодно (см. комментарий в тесте закрепления отчёта).
    """
    out: set = set()
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= _numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= _numbers(v)
    return out


@pytest_asyncio.fixture
async def seed_two_periods(ids):
    """Объект с папкой и ДВУМЯ отчётами одной формы + файл без выпуска.

    Нужен для сборки «по конкретному файлу»: чтобы проверить закрепление, мало
    иметь данные — нужны два разных отчёта, иначе «показал свой» и «показал
    последний» неотличимы.
    """
    async with db.acquire() as conn:
        await _drop_doc_fixture(conn)
        oid = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_doc_obj') returning id", ids["org"])
        fid = await conn.fetchval(
            "insert into folders(organization_id,object_id,name) values($1,$2,'ztest_doc_folder') returning id",
            ids["org"], oid)
        await conn.execute(
            "insert into canonical_fields(object_id, code, name, data_type) "
            "values($1,'plan','План','number') on conflict do nothing", oid)
        docs = {}
        for i, (day, val) in enumerate((("2026-03-02", 700), ("2026-03-09", 900))):
            doc = await conn.fetchval(
                "insert into documents(organization_id, folder_id, original_filename, source_type, "
                "reporting_period_start, uploaded_by) values($1,$2,$3,'xlsx',$4::text::date,$5) returning id",
                ids["org"], fid, f"ztest_doc_{day}.xlsx", day, ids["admin"])
            ver = await conn.fetchval(
                "insert into document_versions(document_id, version_no, storage_path, checksum, "
                "file_size_bytes, uploaded_by) values($1,1,$2,$3,10,$4) returning id",
                doc, f"documents/ztest_doc_{i}", f"ztest_doc_sum_{i}", ids["admin"])
            rel = await conn.fetchval(
                "insert into dataset_releases(organization_id, code, name, status, reporting_period_start, "
                "created_by, object_id, source_document_version_id) "
                "values($1,'ztest_doc_ds','Форма','released',$2::text::date,$3,$4,$5) returning id",
                ids["org"], day, ids["admin"], oid, ver)
            await conn.execute(
                "insert into dataset_release_fields(dataset_release_id, canonical_field_code) "
                "values($1,'plan')", rel)
            await conn.execute(
                "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
                "values($1,0,'Итого','plan',$2)", rel, val)
            docs[day] = str(doc)
        # Файл, из которого данные ещё не выпускали: сборка по нему должна
        # объяснить причину, а не отдать пустой дашборд.
        empty = await conn.fetchval(
            "insert into documents(organization_id, folder_id, original_filename, source_type, "
            "reporting_period_start, uploaded_by) values($1,$2,'ztest_doc_empty.xlsx','xlsx','2026-03-16',$3) "
            "returning id", ids["org"], fid, ids["admin"])
    yield {"object_id": str(oid), "folder_id": str(fid),
           "doc_id": docs["2026-03-02"], "old_period": "2026-03-02",
           "old_value": 700, "new_value": 900, "empty_doc_id": str(empty)}
    async with db.acquire() as conn:
        await _drop_doc_fixture(conn)


async def _drop_doc_fixture(conn):
    await conn.execute("delete from dataset_values where dataset_release_id in "
                       "(select id from dataset_releases where code='ztest_doc_ds')")
    await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                       "(select id from dataset_releases where code='ztest_doc_ds')")
    await conn.execute("delete from dataset_releases where code='ztest_doc_ds'")
    await conn.execute("delete from document_versions where document_id in "
                       "(select id from documents where original_filename like 'ztest_doc_%')")
    await conn.execute("delete from documents where original_filename like 'ztest_doc_%'")
    await conn.execute("delete from folders where name='ztest_doc_folder'")
    await conn.execute("delete from canonical_fields where object_id in "
                       "(select id from objects where name='ztest_doc_obj')")
    await conn.execute("delete from objects where name='ztest_doc_obj'")


def _dataset(periods):
    return [{
        "code": "t_ds", "name": "Форма", "periods": len(periods), "releases": len(periods),
        "fields": [{"code": "plan", "name": "План"}, {"code": "fact", "name": "Факт"}],
        "period_dates": periods,
    }]


def test_period_pages_only_by_explicit_choice():
    """Молча 15 страниц не собираем — дашборд стало бы невозможно открыть."""
    ds = _dataset(["2026-08-05", "2026-07-29", "2026-07-22"])
    specs = _suggest.plan_auto_build(ds, None)
    assert not [s for s in specs if s["page"].startswith(_suggest.PAGE_PERIOD_PREFIX)]

    sel = {"t_ds": {"fields": ["plan", "fact"], "blocks": list(_suggest.BLOCKS),
                    "views": {}, "periods": ["2026-07-29"]}}
    specs = _suggest.plan_auto_build(ds, sel)
    pages = {s["page"] for s in specs if s["page"].startswith(_suggest.PAGE_PERIOD_PREFIX)}
    assert pages == {"Отчёт за 29.07.2026"}, pages


def test_period_widgets_are_pinned_to_that_date():
    """У виджета страницы-среза закреплена дата, у сводного — нет.

    Без этого страница «за 29.07» показывала бы данные последней недели, то
    есть врала бы заголовком.
    """
    ds = _dataset(["2026-08-05", "2026-07-29"])
    sel = {"t_ds": {"fields": ["plan"], "blocks": list(_suggest.BLOCKS),
                    "views": {}, "periods": ["2026-07-29"]}}
    specs = _suggest.plan_auto_build(ds, sel)
    period_specs = [s for s in specs if s["page"].startswith(_suggest.PAGE_PERIOD_PREFIX)]
    summary_specs = [s for s in specs if not s["page"].startswith(_suggest.PAGE_PERIOD_PREFIX)]

    assert period_specs, specs
    assert all(s["config"].get("period") == "2026-07-29" for s in period_specs)
    assert all("period" not in s["config"] for s in summary_specs), "сводные страницы не закрепляются"


def test_unknown_and_extra_periods_are_ignored():
    """Дата, которой нет в данных, страницу не создаёт; число страниц ограничено."""
    dates = [f"2026-0{m}-0{d}" for m in (4, 5) for d in range(1, 8)]
    ds = _dataset(dates)
    sel = {"t_ds": {"fields": ["plan"], "blocks": list(_suggest.BLOCKS), "views": {},
                    "periods": [*dates, "1999-01-01"]}}
    specs = _suggest.plan_auto_build(ds, sel)
    pages = {s["page"] for s in specs if s["page"].startswith(_suggest.PAGE_PERIOD_PREFIX)}
    assert "Отчёт за 01.01.1999" not in pages
    assert len(pages) == _suggest.MAX_AUTO_PERIOD_PAGES


async def test_pinned_widget_reads_its_own_period(client, admin_headers, seed_dataset):
    """Сквозная проверка: закреплённый виджет считает данные СВОЕЙ недели.

    Фикстура даёт два выпуска: 01.01 (plan −5 у каждой строки) и 02.01 (plan
    как есть). Виджет без периода должен показать свежий выпуск, с периодом —
    старый.
    """
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_period_dash"})
    did = r.json()["id"]
    r = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "Стр"})
    pid = r.json()["id"]
    try:
        latest = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "Сводный", "widget_type": "kpi",
            "config": {"dataset_code": seed_dataset["code"], "value_field": "plan"}})
        pinned = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "За 01.01", "widget_type": "kpi",
            "config": {"dataset_code": seed_dataset["code"], "value_field": "plan",
                       "period": "2026-01-01"}})

        a = (await client.get(f"/widgets/{latest.json()['id']}/data", headers=admin_headers)).json()
        b = (await client.get(f"/widgets/{pinned.json()['id']}/data", headers=admin_headers)).json()

        assert a["value"] == seed_dataset["plan_sum"], a
        # Старый выпуск: у каждой строки на 5 меньше.
        assert b["value"] == seed_dataset["plan_sum"] - 5 * len(seed_dataset["rows"]), b
        assert b["as_of"] == "2026-01-01", "подпись свежести должна называть закреплённую дату"
        assert b.get("period_locked") is True, "страница-срез обязана честно говорить, что не обновляется"
        assert a.get("period_locked") is None
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


# --- Сборка по КОНКРЕТНОМУ файлу (объект → папка → файл) --------------------- #
# Запрос заказчика: выбрать в мастере объект, папку и файл и собрать дашборд по
# этому отчёту. Ключевое решение: выбранный файл ЗАКРЕПЛЯЕТ дашборд за своей
# отчётной датой. Человек указал отчёт за конкретную неделю — значит и через
# неделю там должна быть она, иначе это уже другой отчёт под тем же названием.
async def test_build_by_document_pins_its_report(client, admin_headers, ids, seed_two_periods):
    """Дашборд по файлу показывает его цифры и не уезжает на свежие данные."""
    doc_id, old_period, old_value, new_value = (
        seed_two_periods["doc_id"], seed_two_periods["old_period"],
        seed_two_periods["old_value"], seed_two_periods["new_value"])

    plan = await client.post("/dashboards/auto/plan", headers=admin_headers,
                             json={"object_id": seed_two_periods["object_id"], "document_id": doc_id})
    assert plan.status_code == 200, plan.text
    assert plan.json()["widgets"] > 0

    r = await client.post("/dashboards/auto", headers=admin_headers,
                          json={"object_id": seed_two_periods["object_id"], "document_id": doc_id,
                                "name": "ztest_by_doc"})
    assert r.status_code in (200, 201), r.text
    did = r.json()["dashboard_id"]
    try:
        async with db.acquire() as conn:
            pinned, free = await conn.fetchrow(
                "select count(*) filter (where config->>'period'=$2) , "
                "count(*) filter (where config->>'period' is null) "
                "from widgets where dashboard_id=$1::uuid", did, old_period)
        assert free == 0, "все виджеты обязаны быть закреплены за выбранным отчётом"
        assert pinned > 0

        pages = (await client.get(f"/dashboards/{did}", headers=admin_headers)).json()["pages"]
        data = (await client.get(f"/dashboard-pages/{pages[0]['id']}/data",
                                 headers=admin_headers)).json()
        # 🔴 Сравниваем ЧИСЛА, а не подстроки JSON. Прежняя проверка искала
        # «900» в тексте всего ответа, а там лежат и идентификаторы виджетов:
        # uuid состоит из тех же 0-9a-f, и тройка цифр попадает в них случайно.
        # Замер: у страницы из десятка виджетов это происходит примерно в 7 %
        # прогонов — тест падал «сам по себе» раз в десяток запусков и выглядел
        # как чужая регрессия.
        values = _numbers(data)
        assert float(old_value) in values, "показаны цифры ВЫБРАННОГО отчёта"
        assert float(new_value) not in values, "свежий отчёт сюда попадать не должен"

        # Снятая галочка «закрепить» — осознанный выбор: состав тот же, данные
        # обновляемые.
        r2 = await client.post("/dashboards/auto", headers=admin_headers,
                               json={"object_id": seed_two_periods["object_id"], "document_id": doc_id,
                                     "lock_period": False, "name": "ztest_by_doc_free"})
        did2 = r2.json()["dashboard_id"]
        async with db.acquire() as conn:
            free2 = await conn.fetchval(
                "select count(*) from widgets where dashboard_id=$1::uuid "
                "and config->>'period' is null", did2)
        assert free2 > 0, "без закрепления виджеты читают последний выпуск"
        await purge_dashboard(did2)
    finally:
        await purge_dashboard(did)


async def test_build_by_document_without_release_is_explained(client, admin_headers, seed_two_periods):
    """Файл без выпущенных данных — понятный отказ, а не пустой дашборд."""
    r = await client.post("/dashboards/auto/plan", headers=admin_headers,
                          json={"object_id": seed_two_periods["object_id"],
                                "document_id": seed_two_periods["empty_doc_id"]})
    assert r.status_code == 400
    assert "не выпускали данные" in r.json()["detail"]
