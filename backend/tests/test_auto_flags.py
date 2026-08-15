"""Ручное управление автоматикой: галочки, свежесть, недостающие показатели.

«Автообновление» означает три разные вещи, и человек управляет ими раздельно:
цифры в виджетах (всегда, тумблера нет), подготовка выпуска из нового файла
(галочка на папке) и подсказки о показателях, которых нет на дашборде (галочка
на дашборде). Здесь проверяется, что галочки действительно управляют, а не
только рисуются.
"""
import io

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

import pytest_asyncio

from app import db
from app.modules.documents import storage
from app.modules.ingestion import queue


def _xlsx() -> bytes:
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["Субъект", "Обращения"])
    ws.append(["ДНР", 100])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


@pytest_asyncio.fixture
async def folder(client, admin_headers):
    r = await client.post("/objects", headers=admin_headers, json={"name": "ztest_flags_obj"})
    oid = r.json()["id"]
    r = await client.post(f"/objects/{oid}/folders", headers=admin_headers, json={"name": "ztest_flags_folder"})
    fid = r.json()["id"]
    yield {"object_id": oid, "folder_id": fid}
    async with db.acquire() as conn:
        await conn.execute("delete from extraction_jobs where document_version_id in "
                           "(select dv.id from document_versions dv join documents d on d.id=dv.document_id "
                           " where d.folder_id=$1::uuid)", fid)
        await conn.execute("delete from document_versions where document_id in "
                           "(select id from documents where folder_id=$1::uuid)", fid)
        await conn.execute("delete from documents where folder_id=$1::uuid", fid)
        await conn.execute("delete from folders where id=$1::uuid", fid)
        await conn.execute("delete from objects where id=$1::uuid", oid)


@pytest.fixture
def offline_queue(monkeypatch):
    queued: list[str] = []

    async def fake(job_id: str) -> None:
        queued.append(job_id)

    monkeypatch.setattr(queue, "enqueue_extraction", fake)
    return queued


async def test_auto_prepare_off_stops_recognition(client, admin_headers, folder, monkeypatch, offline_queue):
    """Галочка выключена — файл принимается, но сам не распознаётся."""
    monkeypatch.setattr(storage, "put_object", lambda n, d, c: f"documents/{n}")
    oid, fid = folder["object_id"], folder["folder_id"]

    r = await client.patch(f"/objects/{oid}/folders/{fid}", headers=admin_headers,
                           json={"auto_prepare": False})
    assert r.status_code == 200, r.text
    assert r.json()["auto_prepare"] is False
    assert r.json()["name"] == "ztest_flags_folder", "правка частичная: имя не должно потеряться"

    r = await client.post(f"/folders/{fid}/documents", headers=admin_headers,
                          files={"file": ("a.xlsx", _xlsx(), "application/vnd.ms-excel")},
                          data={"reporting_period_start": "2026-07-22"})
    assert r.status_code == 201, r.text
    assert r.json()["extraction_job_id"] is None, "с выключенной галочкой распознавание не запускается"
    assert offline_queue == []

    # Включаем обратно — следующий файл готовится сам.
    r = await client.patch(f"/objects/{oid}/folders/{fid}", headers=admin_headers,
                           json={"auto_prepare": True})
    assert r.status_code == 200
    r = await client.post(f"/folders/{fid}/documents", headers=admin_headers,
                          files={"file": ("b.xlsx", _xlsx(), "application/vnd.ms-excel")},
                          data={"reporting_period_start": "2026-07-29"})
    assert r.json()["extraction_job_id"], r.json()
    assert len(offline_queue) == 1


async def test_folders_list_exposes_flag(client, admin_headers, folder):
    r = await client.get(f"/objects/{folder['object_id']}/folders", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()[0]["auto_prepare"] is True, "по умолчанию подготовка включена"


async def test_dashboard_freshness_and_missing_fields(client, admin_headers, seed_dataset, ids):
    """Свежесть считается по датасетам виджетов; неиспользованные поля видны."""
    r = await client.post("/dashboards", headers=admin_headers, json={"name": "ztest_flags_dash"})
    did = r.json()["id"]
    try:
        r = await client.post(f"/dashboards/{did}/pages", headers=admin_headers, json={"name": "Стр"})
        pid = r.json()["id"]

        # Пока виджетов нет — свежести тоже нет: дашборд ни на чём не стоит.
        r = await client.get(f"/dashboards/{did}/freshness", headers=admin_headers)
        assert r.status_code == 200 and r.json()["as_of"] is None

        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers, json={
            "name": "План", "widget_type": "kpi",
            "config": {"dataset_code": seed_dataset["code"], "value_field": "plan"}})

        r = await client.get(f"/dashboards/{did}/freshness", headers=admin_headers)
        fresh = r.json()
        assert fresh["as_of"], fresh
        assert fresh["datasets"] == 1

        # «fact» на дашборде не показан — система должна о нём сказать.
        r = await client.get(f"/dashboards/{did}/missing-fields", headers=admin_headers)
        codes = {f["code"] for f in r.json()["fields"]}
        assert "fact" in codes, r.json()
        assert "plan" not in codes, "показанное на дашборде не считается недостающим"

        # Галочку подсказок можно выключить — она хранится на дашборде.
        r = await client.patch(f"/dashboards/{did}", headers=admin_headers,
                               json={"suggest_new_fields": False})
        assert r.status_code == 200 and r.json()["suggest_new_fields"] is False
        r = await client.get(f"/dashboards/{did}", headers=admin_headers)
        assert r.json()["dashboard"]["suggest_new_fields"] is False
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)


async def test_auto_build_binds_dashboard_to_folder(client, admin_headers, folder, monkeypatch, offline_queue):
    """Мастер сам ставит дашборд в папку объекта: он и так знает, откуда данные.

    Раньше человек шёл в дашборд и назначал папку отдельным действием, а до тех
    пор дашборд висел «без папки» и не находился фильтром по банку отделов.
    """
    from app.modules.ingestion import service as ing

    content = _xlsx()
    monkeypatch.setattr(storage, "put_object", lambda n, d, c: f"documents/{n}")
    monkeypatch.setattr(storage, "get_object", lambda p: content)
    oid, fid = folder["object_id"], folder["folder_id"]

    r = await client.post(f"/folders/{fid}/documents", headers=admin_headers,
                          files={"file": ("f.xlsx", content, "application/vnd.ms-excel")},
                          data={"reporting_period_start": "2026-07-22"})
    job_id = r.json()["extraction_job_id"]
    await ing.run_extraction(job_id)
    job = (await client.get(f"/extraction-jobs/{job_id}", headers=admin_headers)).json()
    t = job["tables"][0]
    r = await client.post(f"/extraction-jobs/{job_id}/release", headers=admin_headers, json={
        "table_id": t["id"], "code": "ztest_flags_ds", "name": "Форма",
        "reporting_period_start": "2026-07-22",
        "fields": [
            {"column_index": 0, "field_code": "subj", "field_name": "Субъект",
             "data_type": "text", "is_row_label": True},
            {"column_index": 1, "field_code": "obr", "field_name": "Обращения",
             "data_type": "number", "is_row_label": False},
        ],
        "layout": {"data_rect": [0, 0, 1, 1], "header_rows": 1,
                   "orientation": "columns", "skip_rows": []},
    })
    assert r.status_code == 201, r.text

    r = await client.post("/dashboards/auto", headers=admin_headers, json={"object_id": oid})
    assert r.status_code in (200, 201), r.text
    did = r.json()["dashboard_id"]
    try:
        d = (await client.get(f"/dashboards/{did}", headers=admin_headers)).json()["dashboard"]
        assert str(d["folder_id"]) == fid, "дашборд должен встать в папку, откуда пришли данные"
        assert d["folder_name"] == "ztest_flags_folder"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from widgets where dashboard_id=$1::uuid", did)
            await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", did)
            await conn.execute("delete from securable_objects where object_id=$1::uuid", did)
            await conn.execute("delete from dashboards where id=$1::uuid", did)
            await conn.execute("delete from dataset_values where dataset_release_id in "
                               "(select id from dataset_releases where object_id=$1::uuid)", oid)
            await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                               "(select id from dataset_releases where object_id=$1::uuid)", oid)
            await conn.execute("delete from object_layout_templates where object_id=$1::uuid", oid)
            await conn.execute("delete from dataset_releases where object_id=$1::uuid", oid)
            await conn.execute("delete from canonical_fields where object_id=$1::uuid", oid)
