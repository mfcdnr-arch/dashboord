"""Мастер, этап 4: расчётные показатели галочками и память выбора.

Две вещи, которые закрывают последний ручной шов в сборке дашборда:
(1) предложенная метрика раньше становилась только черновиком, а виджет по ней
человек добавлял руками — и часто про это забывал;
(2) мастер каждый раз открывался «как в первый раз»: при недельной форме одни
и те же галочки снимались заново каждую неделю.
"""
import io

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

import pytest_asyncio

from app import db
from app.modules.documents import storage
from app.modules.ingestion import queue
from app.modules.ingestion import service as ing


def _form(plan: int, fact: int) -> bytes:
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["Субъект",
               "Количество записавшихся · План (до 1 сентября 2026 г.)",
               "Количество записавшихся · Факт · нарастающим итогом"])
    ws.append(["ДНР", plan, fact])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


@pytest.fixture
def offline_queue(monkeypatch):
    async def fake(job_id: str) -> None:
        return None
    monkeypatch.setattr(queue, "enqueue_extraction", fake)


@pytest_asyncio.fixture
async def object_with_form(client, admin_headers, monkeypatch, offline_queue):
    """Объект с выпущенной формой «план + факт» — по ней находится % выполнения."""
    r = await client.post("/objects", headers=admin_headers, json={"name": "ztest_wiz_obj"})
    oid = r.json()["id"]
    r = await client.post(f"/objects/{oid}/folders", headers=admin_headers, json={"name": "ztest_wiz_folder"})
    fid = r.json()["id"]

    content = _form(1000, 250)
    monkeypatch.setattr(storage, "put_object", lambda n, d, c: f"documents/{n}")
    monkeypatch.setattr(storage, "get_object", lambda p: content)
    r = await client.post(f"/folders/{fid}/documents", headers=admin_headers,
                          files={"file": ("w.xlsx", content, "application/vnd.ms-excel")},
                          data={"reporting_period_start": "2026-07-22"})
    job_id = r.json()["extraction_job_id"]
    await ing.run_extraction(job_id)
    job = (await client.get(f"/extraction-jobs/{job_id}", headers=admin_headers)).json()
    t = job["tables"][0]
    r = await client.post(f"/extraction-jobs/{job_id}/release", headers=admin_headers, json={
        "table_id": t["id"], "code": "ztest_wiz_ds", "name": "Форма",
        "reporting_period_start": "2026-07-22",
        "fields": [
            {"column_index": 0, "field_code": "subj", "field_name": "Субъект",
             "data_type": "text", "is_row_label": True},
            {"column_index": 1, "field_code": "zap_plan",
             "field_name": "Количество записавшихся · План (до 1 сентября 2026 г.)",
             "data_type": "number", "is_row_label": False},
            {"column_index": 2, "field_code": "zap_fact",
             "field_name": "Количество записавшихся · Факт · нарастающим итогом",
             "data_type": "number", "is_row_label": False},
        ],
        "layout": {"data_rect": [0, 0, 1, 2], "header_rows": 1,
                   "orientation": "columns", "skip_rows": []},
    })
    assert r.status_code == 201, r.text

    yield {"object_id": oid, "folder_id": fid}

    async with db.acquire() as conn:
        await conn.execute("delete from metric_versions where metric_id in "
                           "(select id from metrics where organization_id=(select organization_id from objects where id=$1::uuid) "
                           " and code like 'ztest%')", oid)
        await conn.execute("delete from dataset_values where dataset_release_id in "
                           "(select id from dataset_releases where object_id=$1::uuid)", oid)
        await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                           "(select id from dataset_releases where object_id=$1::uuid)", oid)
        await conn.execute("delete from object_layout_templates where object_id=$1::uuid", oid)
        await conn.execute("delete from dataset_releases where object_id=$1::uuid", oid)
        await conn.execute("delete from canonical_fields where object_id=$1::uuid", oid)
        await conn.execute("delete from extraction_jobs where document_version_id in "
                           "(select dv.id from document_versions dv join documents d on d.id=dv.document_id "
                           " where d.folder_id=$1::uuid)", fid)
        await conn.execute("delete from document_versions where document_id in "
                           "(select id from documents where folder_id=$1::uuid)", fid)
        await conn.execute("delete from documents where folder_id=$1::uuid", fid)
        await conn.execute("delete from folders where id=$1::uuid", fid)
        await conn.execute("delete from objects where id=$1::uuid", oid)


async def _drop_dashboard(did):
    async with db.acquire() as conn:
        await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
        await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
        await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
        await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_wizard_offers_metrics_from_data(client, admin_headers, object_with_form):
    """Мастер показывает расчётные показатели, найденные по самим данным."""
    r = await client.post("/dashboards/auto/plan", headers=admin_headers,
                          json={"object_id": object_with_form["object_id"]})
    assert r.status_code == 200, r.text
    metrics = r.json().get("metrics") or []
    assert metrics, "по паре «план + факт» обязан найтись процент выполнения"
    assert all(m.get("formula") for m in metrics)
    # Предложения проверены расчётом ещё в разделе «Метрики» — сюда попадают
    # только считающиеся, поэтому у них есть значение.
    assert any(m.get("preview_value") is not None for m in metrics)


async def test_picked_metric_becomes_draft_and_widget(client, admin_headers, object_with_form):
    """Отмеченная метрика заводится черновиком И появляется карточкой.

    Раньше принятие предложения давало только черновик метрики — виджет по ней
    человек добавлял руками, и шаг терялся.
    """
    oid = object_with_form["object_id"]
    plan = (await client.post("/dashboards/auto/plan", headers=admin_headers,
                              json={"object_id": oid})).json()
    code = (plan["metrics"] or [])[0]["code"]

    r = await client.post("/dashboards/auto", headers=admin_headers,
                          json={"object_id": oid, "metrics": [code]})
    assert r.status_code in (200, 201), r.text
    did = r.json()["dashboard_id"]
    assert r.json()["metrics"] == 1
    try:
        async with db.acquire() as conn:
            metric = await conn.fetchrow("select id from metrics where code=$1", code)
            assert metric is not None, "метрика должна быть заведена"
            ver = await conn.fetchrow(
                "select status from metric_versions where metric_id=$1", metric["id"])
            assert ver["status"] == "draft", "порядок согласования не нарушаем — только черновик"

            w = await conn.fetchrow(
                "select config from widgets where dashboard_id=$1::uuid "
                "and config->>'metric_code'=$2", did, code)
            assert w is not None, "по выбранной метрике должна появиться карточка"
    finally:
        await _drop_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute("delete from metric_versions where metric_id in "
                               "(select id from metrics where code=$1)", code)
            await conn.execute("delete from metrics where code=$1", code)


async def test_selection_is_remembered_for_next_time(client, admin_headers, object_with_form):
    """Выбор сохраняется на объекте и возвращается следующим открытием мастера."""
    oid = object_with_form["object_id"]
    selection = {"ztest_wiz_ds": {"fields": ["zap_fact"], "blocks": ["kpi"], "views": {}}}

    r = await client.post("/dashboards/auto", headers=admin_headers,
                          json={"object_id": oid, "selection": selection})
    did = r.json()["dashboard_id"]
    try:
        plan = (await client.post("/dashboards/auto/plan", headers=admin_headers,
                                  json={"object_id": oid})).json()
        saved = plan.get("saved_selection")
        assert saved, "мастер должен помнить прошлый выбор"
        assert saved["selection"]["ztest_wiz_ds"]["fields"] == ["zap_fact"]
        assert saved["selection"]["ztest_wiz_ds"]["blocks"] == ["kpi"]
    finally:
        await _drop_dashboard(did)
