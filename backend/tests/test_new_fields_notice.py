"""Этап 5: «в форме появилась новая графа — добавить виджет?» (решение 23.09.2026).

Правило «графа новая» (ingestion/new_fields.py) проверяется на ловушках,
найденных замером на настоящих данных РЦО: снятые выпуски, загрузка истории,
возврат прежней графы, безымянные столбцы, переименование, удалённый выпуск.
Затем — сквозной ручной выпуск через HTTP и честная подсказка на дашборде
(было 359 «непоказанных» граф на РЦО, должно остаться то, что появилось после
сборки).
"""
from datetime import date

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db  # noqa: E402
from app.modules.ingestion import new_fields as nf  # noqa: E402
from app.modules.ingestion import service  # noqa: E402
from conftest import purge_dashboard  # noqa: E402
from pipeline_helpers import (  # noqa: E402,F401 — фикстуры подключаются импортом
    WEEK1, WEEK2, _form, _release, _upload, folder, offline_queue,
)

CODE = "ztest_nf_ds"


async def _purge(conn, code: str, oid=None) -> None:
    if oid:
        await conn.execute(
            "delete from notification_recipients where notification_event_id in "
            "(select id from notification_events where entity_type='object' and entity_id=$1::uuid)", oid)
        await conn.execute(
            "delete from notification_events where entity_type='object' and entity_id=$1::uuid", oid)
    await conn.execute("delete from dataset_new_fields where code=$1", code)
    await conn.execute("delete from dataset_values where dataset_release_id in "
                       "(select id from dataset_releases where code=$1)", code)
    await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                       "(select id from dataset_releases where code=$1)", code)
    await conn.execute("delete from dataset_releases where code=$1", code)
    if oid:
        await conn.execute("delete from canonical_fields where object_id=$1::uuid", oid)
        await conn.execute("delete from objects where id=$1::uuid", oid)


@pytest_asyncio.fixture
async def form(ids):
    async with db.acquire() as conn:
        await conn.execute("delete from objects where name='ztest_nf_obj'")
        await _purge(conn, CODE)
        oid = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_nf_obj') returning id", ids["org"])
    yield {"oid": oid, "org": ids["org"], "admin": ids["admin"]}
    async with db.acquire() as conn:
        await _purge(conn, CODE, oid)


async def _rel(conn, f, period, fields, *, status="validated", declare=True):
    """Выпуск формы: fields = {код: (имя, [числа] или None — текстовая графа)}."""
    rid = await conn.fetchval(
        "insert into dataset_releases(organization_id,code,name,status,reporting_period_start,"
        "created_by,object_id) values($1,$2,'Форма',$3,$4,$5,$6) returning id",
        f["org"], CODE, status, period, f["admin"], f["oid"])
    for code, (name, vals) in fields.items():
        await conn.execute(
            "insert into canonical_fields(object_id,code,name,data_type,created_by) values($1,$2,$3,$4,$5) "
            "on conflict (object_id, code) do update set name=excluded.name",
            f["oid"], code, name, "text" if vals is None else "number", f["admin"])
        for i, v in enumerate(vals if vals is not None else ["нет", "да"]):
            if vals is None:
                await conn.execute(
                    "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,"
                    "value_text) values($1,$2,$3,$4,$5)", rid, i, f"Строка {i}", code, v)
            else:
                await conn.execute(
                    "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,"
                    "value_number) values($1,$2,$3,$4,$5)", rid, i, f"Строка {i}", code, v)
        if declare:
            await conn.execute(
                "insert into dataset_release_fields(dataset_release_id,canonical_field_code) values($1,$2)",
                rid, code)
    return rid


async def _seen(conn, f):
    """Как после штатного пути выпуска: правило просмотрело выпуски формы."""
    await nf.announce(conn, f["org"], CODE)


BASE = {"obr": ("Обращения", [10, 20]), "uved": ("Уведомления", [1, 2])}
JUL1, JUL8, JUL15, JUN1 = date(2026, 7, 1), date(2026, 7, 8), date(2026, 7, 15), date(2026, 6, 1)


async def test_first_release_of_a_form_is_not_news(form):
    """Первый выпуск формы — это «новая форма» (этап 4), а не новые графы."""
    async with db.acquire() as conn:
        await _rel(conn, form, JUL1, BASE)
        assert await nf.detect(conn, form["org"], CODE) is None


async def test_new_numeric_field_is_detected_once(form):
    """Графа с числами, которой не было ни в одном прежнем выпуске, — новая;
    повторная проверка её не объявляет (журнал)."""
    async with db.acquire() as conn:
        await _rel(conn, form, JUL1, BASE)
        await _seen(conn, form)
        # Новые услуги в первый день — нули: «ненулевое» правило их потеряло бы.
        await _rel(conn, form, JUL8, {**BASE, "zap": ("Записались", [0, 0])})
        found = await nf.announce(conn, form["org"], CODE)
        assert found and [f["name"] for f in found["fields"]] == ["Записались"], found
        assert found["notice_id"] is None, "форму не смотрит ни один дашборд — уведомлять некого"
        assert await conn.fetchval(
            "select count(*) from dataset_new_fields where code=$1 and field_code='zap'", CODE) == 1, \
            "запись в журнале есть и без уведомления — иначе графа объявилась бы задним числом"
        assert await nf.announce(conn, form["org"], CODE) is None, "повтор ничего не объявляет"


async def test_superseded_history_and_returning_fields_are_not_news(form):
    """Ловушки замера: снятый выпуск, загрузка истории, возврат прежней графы."""
    async with db.acquire() as conn:
        # Графа была в выпуске, который потом сняли, — её уже «видели».
        await _rel(conn, form, JUL1, {**BASE, "old": ("Прежняя услуга", [5, 5])}, status="superseded")
        await _rel(conn, form, JUL1, BASE)
        await _seen(conn, form)
        await _rel(conn, form, JUL8, {**BASE, "old": ("Прежняя услуга", [3, 4])})
        assert await nf.detect(conn, form["org"], CODE) is None, "возврат прежней графы — не новость"
        await _seen(conn, form)

        # Загрузка истории: выпуск за более ранний период приносит графу,
        # которой в свежем отчёте нет, — это прошлое, а не новость.
        await _rel(conn, form, JUN1, {**BASE, "hist": ("Ушедшая услуга", [7, 7])})
        assert await nf.detect(conn, form["org"], CODE) is None


async def test_text_unnamed_and_undeclared_fields(form):
    """Без чисел и безымянные «Столбец N» не объявляются; графа, у прежнего
    выпуска которой нет объявлений, но есть значения, — не новая."""
    async with db.acquire() as conn:
        await _rel(conn, form, JUL1, {**BASE, "legacy": ("Старая графа", [1, 1])}, declare=False)
        await _seen(conn, form)
        await _rel(conn, form, JUL8, {
            **BASE, "legacy": ("Старая графа", [2, 2]),
            "note": ("Комментарии", None), "stolbec_7": ("Столбец 7", [1, 2])})
        assert await nf.detect(conn, form["org"], CODE) is None


async def test_rename_is_reported_not_hidden(form):
    """Переименование даёт новый код — объявляем, но называем, сколько пропало."""
    async with db.acquire() as conn:
        await _rel(conn, form, JUL1, {**BASE, "svc_a": ("Услуга А", [1, 2])})
        await _seen(conn, form)
        await _rel(conn, form, JUL8, {**BASE, "svc_a2": ("(101) Услуга А", [1, 2])})
        found = await nf.detect(conn, form["org"], CODE)
        assert found and found["gone"] == 1, "пропала одна графа — подсказка про переименование"


async def test_deleted_release_does_not_revive_the_field(form):
    """Выпуск, принёсший графу, удалили — при следующем появлении она не «новая»."""
    async with db.acquire() as conn:
        await _rel(conn, form, JUL1, BASE)
        await _seen(conn, form)
        r2 = await _rel(conn, form, JUL8, {**BASE, "zap": ("Записались", [1, 1])})
        assert await nf.announce(conn, form["org"], CODE)
        await conn.execute("delete from dataset_values where dataset_release_id=$1", r2)
        await conn.execute("delete from dataset_releases where id=$1", r2)
        await _rel(conn, form, JUL15, {**BASE, "zap": ("Записались", [2, 2])})
        assert await nf.detect(conn, form["org"], CODE) is None


async def test_notice_goes_to_editors_of_watched_forms_only(client, admin_headers, form):
    """Уведомление — только если форму смотрит дашборд с включённой подсказкой."""
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_nf_dash", "force": True})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                                 json={"name": "Стр"})).json()["id"]
        async with db.acquire() as conn:
            await _rel(conn, form, JUL1, BASE)
            await _seen(conn, form)
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "Обращения", "widget_type": "kpi",
            "config": {"dataset_code": CODE, "value_field": "obr"}})

        # Подсказки на дашборде выключены — человек просил не напоминать.
        await client.patch(f"/dashboards/{did}", headers=admin_headers, json={"suggest_new_fields": False})
        async with db.acquire() as conn:
            await _rel(conn, form, JUL8, {**BASE, "zap": ("Записались", [0, 1])})
            found = await nf.announce(conn, form["org"], CODE)
            assert found and found["notice_id"] is None

        await client.patch(f"/dashboards/{did}", headers=admin_headers, json={"suggest_new_fields": True})
        async with db.acquire() as conn:
            await _rel(conn, form, JUL15, {**BASE, "zap": ("Записались", [1, 1]),
                                           "ved": ("Выдано", [3, 3])})
            found = await nf.announce(conn, form["org"], CODE)
            assert found and found["notice_id"], found
            assert [f["name"] for f in found["fields"]] == ["Выдано"], \
                "о «Записались» уже объявлено, второй раз — нет"
            ev = await conn.fetchrow(
                "select event_type, entity_type, entity_id, payload from notification_events where id=$1::uuid",
                found["notice_id"])
            assert ev["event_type"] == nf.EVENT and ev["entity_type"] == "object"
            assert str(ev["entity_id"]) == str(form["oid"])
            import json as _json
            pl = _json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
            assert pl["dashboards"][0]["id"] == did and pl["total"] == 1
            assert await conn.fetchval(
                "select count(*) from notification_recipients where notification_event_id=$1::uuid "
                "and user_id=$2", found["notice_id"], form["admin"]) == 1

        r = await client.get("/notifications", headers=admin_headers)
        item = next(i for i in r.json()["items"] if i["event_type"] == nf.EVENT)
        assert item["label"] == "В форме появились новые графы", "подпись типа, а не сырой код"
    finally:
        await purge_dashboard(did)


async def test_editors_are_the_ones_who_can_add_widgets(form):
    """Получатели — роли `manage`: старший модератор виджет добавить не может."""
    async with db.acquire() as conn:
        users = set(await nf.editor_user_ids(conn, form["org"]))
        roles = await conn.fetch(
            "select distinct u.id, r.code from users u join user_roles ur on ur.user_id=u.id "
            "join roles r on r.id=ur.role_id where u.organization_id=$1 and u.is_active", form["org"])
        can = {r["id"] for r in roles if r["code"] in ("superadmin", "admin", "moderator")}
        assert users == can


async def test_failed_notice_does_not_cancel_the_release(form, monkeypatch):
    """Сбой объявления не отменяет выпуск — подсказка не вправе сорвать работу."""
    async def boom(*_a, **_k):
        raise RuntimeError("сломанное правило")

    monkeypatch.setattr(nf, "detect", boom)
    async with db.acquire() as conn:
        async with conn.transaction():
            rid = await _rel(conn, form, JUL1, BASE)
            assert await nf.announce_safely(conn, form["org"], CODE) is None
        assert await conn.fetchval("select count(*) from dataset_releases where id=$1", rid) == 1


async def test_manual_release_reports_new_fields(client, admin_headers, folder, monkeypatch, offline_queue):
    """Сквозь HTTP: ручной выпуск формы с новой графой называет её в ответе и
    уведомляет тех, чей дашборд смотрит форму."""
    code = "ztest_nf_http"
    did = None
    # Уборка охватывает ВЕСЬ сценарий: тест, упавший на первом же выпуске,
    # иначе оставлял записи журнала новых граф (найдено прогоном «поломкой»).
    try:
        up1 = await _upload(client, admin_headers, folder["folder_id"], _form(WEEK1), "2026-07-22", monkeypatch)
        await service.run_extraction(up1["extraction_job_id"])
        job = (await client.get(f"/extraction-jobs/{up1['extraction_job_id']}", headers=admin_headers)).json()
        first = await _release(client, admin_headers, job["job_id"], job["tables"][0], code, "2026-07-22")
        assert first.get("new_fields") is None, "первый выпуск формы — не новые графы"

        did = (await client.post("/dashboards", headers=admin_headers,
                                 json={"name": "ztest_nf_http_dash", "force": True})).json()["id"]
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                                 json={"name": "Стр"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "Обращения", "widget_type": "kpi", "config": {"dataset_code": code, "value_field": "obr"}})

        up2 = await _upload(client, admin_headers, folder["folder_id"], _form(WEEK2, extra_col=True),
                            "2026-07-29", monkeypatch)
        await service.run_extraction(up2["extraction_job_id"])
        job2 = (await client.get(f"/extraction-jobs/{up2['extraction_job_id']}", headers=admin_headers)).json()
        t = job2["tables"][0]
        names = ["Субъект", "Обращения", "Уведомления", "Записались"]
        body = {
            "table_id": t["id"], "code": code, "name": "Форма 2026-07-29",
            "reporting_period_start": "2026-07-29", "supersede": False,
            "fields": [{"column_index": i, "field_code": ["subject", "obr", "uved", "zap"][i - 1],
                        "field_name": names[i - 1], "data_type": "text" if i == 1 else "number",
                        "is_row_label": i == 1} for i in range(1, 5)],
            "layout": {"data_rect": t["data_rect"] or [0, 0, 2, 4], "header_rows": 2,
                       "orientation": "columns", "skip_rows": []},
        }
        r = await client.post(f"/extraction-jobs/{job2['job_id']}/release", headers=admin_headers, json=body)
        assert r.status_code == 201, r.text
        news = r.json()["new_fields"]
        assert news and news["fields"] == ["Записались"] and news["notified"], news
        assert news["dashboards"] == ["ztest_nf_http_dash"]

        # Подсказка дашборда называет ту же графу — колокольчик и окно согласны.
        r = await client.get(f"/dashboards/{did}/missing-fields", headers=admin_headers)
        assert [f["code"] for f in r.json()["fields"]] == ["zap"], r.json()
    finally:
        if did:
            await purge_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute("delete from dataset_new_fields where code=$1", code)
            await conn.execute(
                "delete from notification_recipients where notification_event_id in "
                "(select id from notification_events where entity_type='object' and entity_id=$1::uuid)",
                folder["object_id"])
            await conn.execute("delete from notification_events where entity_type='object' "
                               "and entity_id=$1::uuid", folder["object_id"])


async def test_dashboard_hint_shows_only_what_appeared_after_it_was_built(
        client, admin_headers, viewer, form):
    """Подсказка дашборда — то, что появилось ПОСЛЕ сборки: прежние графы, не
    вынесенные в виджеты, — сознательный выбор, а не недостача."""
    async with db.acquire() as conn:
        await _rel(conn, form, JUL1, {**BASE, "old": ("Не вынесено", [1, 1])})
        await _seen(conn, form)
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": "ztest_nf_hint", "force": True})).json()["id"]
    try:
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                                 json={"name": "Стр"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "Обращения", "widget_type": "kpi", "config": {"dataset_code": CODE, "value_field": "obr"}})
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "Первичные данные", "widget_type": "table", "config": {"dataset_code": CODE}})
        r = await client.get(f"/dashboards/{did}/missing-fields", headers=admin_headers)
        assert r.json()["count"] == 0, "графы на момент сборки — не новость"

        async with db.acquire() as conn:
            await _rel(conn, form, JUL8, {**BASE, "old": ("Не вынесено", [2, 2]),
                                          "zap": ("Записались", [0, 3]), "stolbec_9": ("Столбец 9", [1, 1])})
        r = await client.get(f"/dashboards/{did}/missing-fields", headers=admin_headers)
        fields = r.json()["fields"]
        assert [f["code"] for f in fields] == ["zap"], fields
        assert fields[0]["covered_by"] == ["Первичные данные"], \
            "таблица всей формы графу показывает — сказать об этом, а не прятать"
        assert str(fields[0]["first_period"]) == "2026-07-08"

        # Зрителю отмечать нечего; управляющий — «больше не предлагать».
        r = await client.post(f"/dashboards/{did}/missing-fields/review", headers=viewer["headers"],
                              json={"fields": [{"dataset_code": CODE, "code": "zap"}]})
        assert r.status_code == 403
        r = await client.post(f"/dashboards/{did}/missing-fields/review", headers=admin_headers,
                              json={"fields": [{"dataset_code": CODE, "code": "zap"}]})
        assert r.status_code == 200 and r.json()["reviewed"] == 1
        r = await client.get(f"/dashboards/{did}/missing-fields", headers=admin_headers)
        assert r.json()["count"] == 0
    finally:
        await purge_dashboard(did)


# ── Ревью 08.10.2026: «новое» — относительно уже просмотренного ──────────────

async def test_book_with_new_field_in_the_middle_is_announced(form):
    """Книга по листам: графа появилась на втором листе, а не на последнем.
    Прежнее правило видело её в соседнем листе той же книги и молчало всегда
    (на истории РЦО — 101 графа из 105 при недельных поставках)."""
    async with db.acquire() as conn:
        await _rel(conn, form, JUL1, BASE)
        await _seen(conn, form)
        # Одна операция — два листа: графа на обоих.
        await _rel(conn, form, JUL8, {**BASE, "zap": ("Записались", [0, 1])})
        await _rel(conn, form, JUL15, {**BASE, "zap": ("Записались", [2, 3])})
        found = await nf.announce(conn, form["org"], CODE)
        assert found and [f["code"] for f in found["fields"]] == ["zap"], found
        assert await nf.announce(conn, form["org"], CODE) is None, "книга просмотрена — второй раз нечего"


async def test_history_loaded_after_the_freshest_report_is_not_news(form):
    """Сперва свежий отчёт, потом история за прошлые месяцы. Графа свежего
    отчёта, которой нет в истории, не «появилась» — она была с первой загрузки."""
    async with db.acquire() as conn:
        await _rel(conn, form, JUL15, {**BASE, "zap": ("Записались", [1, 1])})
        await _seen(conn, form)
        await _rel(conn, form, JUN1, BASE)
        await _rel(conn, form, JUL1, BASE)
        assert await nf.announce(conn, form["org"], CODE) is None
        assert await conn.fetchval(
            "select count(*) from dataset_releases where code=$1 and new_fields_checked_at is null", CODE) == 0, \
            "история просмотрена — ежедневная страховка не возьмёт её снова"


async def test_failed_announce_is_picked_up_by_the_daily_check(form, monkeypatch):
    """Сорвалось объявление — выпуск остаётся непросмотренным, и ежедневная
    страховка воркера объявляет графу (раньше она повторяла тот же провал)."""
    async with db.acquire() as conn:
        await _rel(conn, form, JUL1, BASE)
        await _seen(conn, form)
        await _rel(conn, form, JUL8, {**BASE, "zap": ("Записались", [1, 1])})

        real = nf.watching_dashboards

        async def boom(*_a, **_k):
            raise RuntimeError("сбой при объявлении")

        monkeypatch.setattr(nf, "watching_dashboards", boom)
        assert await nf.announce_safely(conn, form["org"], CODE) is None
        assert await conn.fetchval(
            "select count(*) from dataset_new_fields where code=$1", CODE) == 0, "журнал откатился"
        assert await conn.fetchval(
            "select count(*) from dataset_releases where code=$1 and new_fields_checked_at is null", CODE) == 1, \
            "отметка «просмотрен» откатилась вместе с объявлением"

        monkeypatch.setattr(nf, "watching_dashboards", real)
        done = await nf.check_all(conn, form["org"])
        assert {"code": CODE, "fields": 1} in done, done


async def _dash_on_form(client, admin_headers, name):
    did = (await client.post("/dashboards", headers=admin_headers,
                             json={"name": name, "force": True})).json()["id"]
    pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                             json={"name": "Стр"})).json()["id"]
    return did, pid


async def _widget(client, admin_headers, pid, name, wtype, cfg):
    r = await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": name, "widget_type": wtype, "config": cfg})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _hint(client, admin_headers, did):
    r = await client.get(f"/dashboards/{did}/missing-fields", headers=admin_headers)
    assert r.status_code == 200, r.text
    return r.json()


async def test_hint_base_is_the_period_at_build_time(client, admin_headers, form):
    """База подсказки — отчётный период на момент сборки, а не время создания:
    история, загруженная после сборки, — тоже база; удаление первого виджета
    базу не сдвигает."""
    async with db.acquire() as conn:
        await _rel(conn, form, JUL8, BASE)
    did, pid = await _dash_on_form(client, admin_headers, "ztest_nf_since")
    try:
        first = await _widget(client, admin_headers, pid, "Обращения", "kpi",
                              {"dataset_code": CODE, "value_field": "obr"})
        async with db.acquire() as conn:
            assert await conn.fetchval(
                "select period from dashboard_form_since where dashboard_id=$1::uuid and code=$2",
                did, CODE) == JUL8, "первый виджет на форме фиксирует её период"
            # История за июнь приходит ПОСЛЕ сборки и приносит «hist».
            await _rel(conn, form, JUN1, {**BASE, "hist": ("Июньская услуга", [4, 4])})
            await _rel(conn, form, JUL15, {**BASE, "hist": ("Июньская услуга", [5, 5]),
                                           "zap": ("Записались", [1, 2])})
        h = await _hint(client, admin_headers, did)
        assert [f["code"] for f in h["fields"]] == ["zap"], \
            "графа из истории до сборки — не новость, хоть история и загружена позже"

        # Второй виджет на той же форме, первый удалён: база прежняя.
        await _widget(client, admin_headers, pid, "Уведомления", "kpi",
                      {"dataset_code": CODE, "value_field": "uved"})
        r = await client.delete(f"/widgets/{first}", headers=admin_headers)
        assert r.status_code in (200, 204), r.text
        h = await _hint(client, admin_headers, did)
        assert [f["code"] for f in h["fields"]] == ["zap"], "неразобранная графа не пропадает"
    finally:
        await purge_dashboard(did)


async def test_field_list_hiding_zeros_does_not_count_as_showing(client, admin_headers, form):
    """«Показатели списком» прячут нули — «уже видна в …» про нулевую графу
    была бы неправдой (на РЦО — 5 из 7 граф подсказки)."""
    async with db.acquire() as conn:
        await _rel(conn, form, JUL1, BASE)
    did, pid = await _dash_on_form(client, admin_headers, "ztest_nf_zero")
    try:
        await _widget(client, admin_headers, pid, "Список", "field_list", {"dataset_code": CODE})
        await _widget(client, admin_headers, pid, "Список с нулями", "field_list",
                      {"dataset_code": CODE, "hide_zero": False})
        async with db.acquire() as conn:
            await _rel(conn, form, JUL8, {**BASE, "zap": ("Записались", [0, 0]),
                                          "ved": ("Выдано", [1, 2])})
        by = {f["code"]: f["covered_by"] for f in (await _hint(client, admin_headers, did))["fields"]}
        assert by["ved"] == ["Список", "Список с нулями"], by
        assert by["zap"] == ["Список с нулями"], by
    finally:
        await purge_dashboard(did)


async def test_review_marks_only_offered_fields_and_can_be_undone(client, admin_headers, form):
    """«Больше не предлагать» отмечает только предложенные графы (произвольные
    пары не раздувают отметки) и снимается кнопкой «вернуть скрытые»."""
    async with db.acquire() as conn:
        await _rel(conn, form, JUL1, BASE)
    did, pid = await _dash_on_form(client, admin_headers, "ztest_nf_review")
    try:
        await _widget(client, admin_headers, pid, "Обращения", "kpi", {"dataset_code": CODE, "value_field": "obr"})
        async with db.acquire() as conn:
            await _rel(conn, form, JUL8, {**BASE, "zap": ("Записались", [1, 1])})
        r = await client.post(f"/dashboards/{did}/missing-fields/review", headers=admin_headers, json={
            "fields": [{"dataset_code": CODE, "code": "zap"}, {"dataset_code": CODE, "code": "nope"},
                       {"dataset_code": "chuzhaya_forma", "code": "zap"}]})
        assert r.status_code == 200 and r.json()["reviewed"] == 1, r.text
        h = await _hint(client, admin_headers, did)
        assert h["count"] == 0 and h["reviewed"] == 1, h

        r = await client.post(f"/dashboards/{did}/missing-fields/review/reset", headers=admin_headers)
        assert r.status_code == 200 and r.json()["returned"] == 1, r.text
        h = await _hint(client, admin_headers, did)
        assert [f["code"] for f in h["fields"]] == ["zap"] and h["reviewed"] == 0, h
    finally:
        await purge_dashboard(did)
