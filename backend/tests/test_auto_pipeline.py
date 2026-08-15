"""Авто-конвейер, кусок 2: файл сам доходит до состояния «данные подготовлены».

Проверяется цепочка, которой раньше не было: загрузка ставит распознавание сама,
воркер сразу сверяет структуру с шаблоном объекта и запоминает вердикт, а список
папки показывает по каждому файлу, готов он к выпуску или требует внимания.

Отдельно — диагноз расхождения: система обязана сказать, ЧТО именно изменилось
в бланке, а не только «форма отличается».
"""
import io

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

import pytest_asyncio

from app import db
from app.modules.documents import storage
from app.modules.ingestion import mapping, queue, service


def _form(rows, extra_col=False, renamed=False) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Форма"
    third = "Обращения граждан" if renamed else "Обращения"
    top = ["№ п/п", "Субъект", third, "Уведомления"] + (["Записались"] if extra_col else [])
    ws.append(top)
    ws.append(["1", "2", "3", "4"] + (["5"] if extra_col else []))
    for r in rows:
        ws.append(list(r) + ([0] if extra_col else []))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


WEEK1 = [("1", "ДНР", 891651, 108584)]
WEEK2 = [("1", "ДНР", 929825, 146758)]


@pytest_asyncio.fixture
async def folder(client, admin_headers):
    r = await client.post("/objects", headers=admin_headers, json={"name": "ztest_pipe_obj"})
    oid = r.json()["id"]
    r = await client.post(f"/objects/{oid}/folders", headers=admin_headers, json={"name": "ztest_pipe_folder"})
    fid = r.json()["id"]
    yield {"object_id": oid, "folder_id": fid}
    async with db.acquire() as conn:
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


@pytest.fixture
def offline_queue(monkeypatch):
    """Очередь без Redis: задания копим, прогоняем вручную — как воркер."""
    queued: list[str] = []

    async def fake(job_id: str) -> None:
        queued.append(job_id)

    monkeypatch.setattr(queue, "enqueue_extraction", fake)
    return queued


async def _upload(client, headers, folder_id, content, period, monkeypatch):
    monkeypatch.setattr(storage, "put_object", lambda name, data, ct: f"documents/{name}")
    monkeypatch.setattr(storage, "get_object", lambda path: content)
    r = await client.post(
        f"/folders/{folder_id}/documents", headers=headers,
        files={"file": (f"f_{period}.xlsx", content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"reporting_period_start": period})
    assert r.status_code == 201, r.text
    return r.json()


async def _release(client, headers, job_id, table, code, period, skip=()):
    cols = [c for c in table["columns"] if c["column_index"] > 0]
    body = {
        "table_id": table["id"], "code": code, "name": f"Форма {period}",
        "reporting_period_start": period,
        "fields": [{
            "column_index": c["column_index"],
            "field_code": ["subject", "obr", "uved"][c["column_index"] - 1],
            "field_name": ["Субъект", "Обращения", "Уведомления"][c["column_index"] - 1],
            "data_type": "text" if c["column_index"] == 1 else "number",
            "is_row_label": c["column_index"] == 1,
        } for c in cols],
        "layout": {"data_rect": table["data_rect"] or [0, 0, 2, 3], "header_rows": 2,
                   "orientation": "columns", "skip_rows": list(skip)},
    }
    r = await client.post(f"/extraction-jobs/{job_id}/release", headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_upload_starts_extraction_itself(client, admin_headers, folder, monkeypatch, offline_queue):
    """Загрузка сама ставит распознавание — отдельного нажатия больше не нужно."""
    up = await _upload(client, admin_headers, folder["folder_id"], _form(WEEK1), "2026-07-22", monkeypatch)
    assert up["extraction_job_id"], "загрузка обязана вернуть заведённое задание"
    assert offline_queue == [up["extraction_job_id"]], "задание должно уйти в очередь воркера"

    # Пока воркер не отработал, в списке видно, что файл в работе.
    r = await client.get(f"/folders/{folder['folder_id']}/documents", headers=admin_headers)
    assert r.json()["items"][0]["pipeline"] == "parsing"

    await service.run_extraction(up["extraction_job_id"])
    r = await client.get(f"/folders/{folder['folder_id']}/documents", headers=admin_headers)
    item = r.json()["items"][0]
    # Шаблона ещё нет — первый файл формы размечает человек.
    assert item["pipeline"] == "needs_markup", item
    assert "разметьте" in item["pipeline_hint"].lower()


async def test_second_week_becomes_ready_by_itself(client, admin_headers, folder, monkeypatch, offline_queue):
    """Вторая неделя доходит до «данные подготовлены» без участия человека."""
    up1 = await _upload(client, admin_headers, folder["folder_id"], _form(WEEK1), "2026-07-22", monkeypatch)
    await service.run_extraction(up1["extraction_job_id"])
    job = (await client.get(f"/extraction-jobs/{up1['extraction_job_id']}", headers=admin_headers)).json()
    await _release(client, admin_headers, job["job_id"], job["tables"][0], "zpipe_code", "2026-07-22")

    up2 = await _upload(client, admin_headers, folder["folder_id"], _form(WEEK2), "2026-07-29", monkeypatch)
    await service.run_extraction(up2["extraction_job_id"])

    r = await client.get(f"/folders/{folder['folder_id']}/documents", headers=admin_headers)
    by_name = {i["original_filename"]: i for i in r.json()["items"]}
    assert by_name["f_2026-07-29.xlsx"]["pipeline"] == "ready", by_name["f_2026-07-29.xlsx"]
    # Первый файл уже выпущен — его состояние другое.
    assert by_name["f_2026-07-22.xlsx"]["pipeline"] == "released"


async def test_changed_form_says_what_changed(client, admin_headers, folder, monkeypatch, offline_queue):
    """Форма изменилась → «требует внимания» и точный диагноз, а не общая фраза."""
    up1 = await _upload(client, admin_headers, folder["folder_id"], _form(WEEK1), "2026-07-22", monkeypatch)
    await service.run_extraction(up1["extraction_job_id"])
    job = (await client.get(f"/extraction-jobs/{up1['extraction_job_id']}", headers=admin_headers)).json()
    await _release(client, admin_headers, job["job_id"], job["tables"][0], "zpipe_code", "2026-07-22")

    up2 = await _upload(client, admin_headers, folder["folder_id"],
                        _form(WEEK2, extra_col=True), "2026-08-05", monkeypatch)
    await service.run_extraction(up2["extraction_job_id"])

    r = await client.get(f"/folders/{folder['folder_id']}/documents", headers=admin_headers)
    item = next(i for i in r.json()["items"] if i["original_filename"] == "f_2026-08-05.xlsx")
    assert item["pipeline"] == "attention", item
    assert "Записались" in item["pipeline_hint"], item["pipeline_hint"]

    # Тот же диагноз доступен конструктору разметки.
    job2 = (await client.get(f"/extraction-jobs/{up2['extraction_job_id']}", headers=admin_headers)).json()
    assert "Записались" in (job2["layout_template"]["diff"] or "")


async def test_release_updates_files_uploaded_earlier(client, admin_headers, folder, monkeypatch, offline_queue):
    """Файлы, залитые ДО первого выпуска, узнают, что разметка для них появилась.

    Вердикт считается один раз после распознавания, а шаблон появляется позже —
    без пересчёта вся пачка так и висела бы с «нужна разметка».
    """
    up1 = await _upload(client, admin_headers, folder["folder_id"], _form(WEEK1), "2026-07-22", monkeypatch)
    up2 = await _upload(client, admin_headers, folder["folder_id"], _form(WEEK2), "2026-07-29", monkeypatch)
    await service.run_extraction(up1["extraction_job_id"])
    await service.run_extraction(up2["extraction_job_id"])

    r = await client.get(f"/folders/{folder['folder_id']}/documents", headers=admin_headers)
    assert {i["pipeline"] for i in r.json()["items"]} == {"needs_markup"}, "шаблона ещё нет"

    job = (await client.get(f"/extraction-jobs/{up1['extraction_job_id']}", headers=admin_headers)).json()
    await _release(client, admin_headers, job["job_id"], job["tables"][0], "zpipe_code", "2026-07-22")

    r = await client.get(f"/folders/{folder['folder_id']}/documents", headers=admin_headers)
    by_name = {i["original_filename"]: i["pipeline"] for i in r.json()["items"]}
    assert by_name["f_2026-07-29.xlsx"] == "ready", by_name
    assert by_name["f_2026-07-22.xlsx"] == "released"


def test_structure_diff_wording():
    """Диагноз читаемый: переименование — переименованием, а не двумя списками."""
    assert "переименована" in mapping.describe_structure_change(
        ["Субъект", "Обращения"], ["Субъект", "Обращения граждан"], 2, 2)
    assert "добавились графы" in mapping.describe_structure_change(
        ["Субъект"], ["Субъект", "Записались", "Отказы"], 2, 2)
    assert "пропали графы" in mapping.describe_structure_change(
        ["Субъект", "Записались", "Отказы"], ["Субъект"], 2, 2)
    assert "порядок" in mapping.describe_structure_change(
        ["Субъект", "Обращения"], ["Обращения", "Субъект"], 2, 2)
    assert "этажей шапки" in mapping.describe_structure_change(
        ["Субъект"], ["Субъект"], 2, 3)


async def test_pickup_pending_takes_orphan_file(client, admin_headers, folder, monkeypatch, offline_queue):
    """Файл, которому не досталось задания, добирается фоновым заданием."""
    from app.modules.ingestion import worker

    up = await _upload(client, admin_headers, folder["folder_id"], _form(WEEK1), "2026-07-22", monkeypatch)
    async with db.acquire() as conn:
        # Имитируем недоступную очередь: задания нет, файл лежит и молчит.
        await conn.execute("delete from extraction_jobs where id=$1::uuid", up["extraction_job_id"])
        await conn.execute(
            "update document_versions set created_at = now() - interval '1 hour' where id=$1::uuid",
            up["version_id"])
    offline_queue.clear()

    await worker.pickup_pending(None)
    assert len(offline_queue) >= 1, "повисший файл должен быть поставлен в очередь"

    async with db.acquire() as conn:
        got = await conn.fetchval(
            "select count(*) from extraction_jobs where document_version_id=$1::uuid", up["version_id"])
    assert got == 1
