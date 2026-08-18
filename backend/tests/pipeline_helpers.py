"""Общее для тестов конвейера «файл → распознавание → выпуск».

Вынесено из test_auto_pipeline.py, когда те же шаги понадобились тестам
видимости авто-выпуска: копия формы и загрузки разошлась бы с оригиналом при
первой же правке конвейера, и один из двух наборов начал бы проверять не то,
что происходит на самом деле.

Фикстуры живут здесь же и импортируются в тестовые модули по имени — в
conftest их не выносим: они нужны двум файлам из сорока, а общий conftest и
так велик.
"""
import io

import pytest
import pytest_asyncio

from app import db
from app.modules.documents import storage
from app.modules.ingestion import queue


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


async def purge_release_traces(conn, object_id) -> None:
    """Убрать за собой уведомления и записи журнала по выпускам объекта.

    Вызывать ДО удаления самих выпусков: и уведомления, и аудит ссылаются на
    выпуск логически, без внешнего ключа, поэтому каскад их не заберёт, а
    оставшееся событие указывает в никуда — ровно тот мусор, из-за которого
    15.08 заводили `prune_notifications` (в бою его подчищает еженедельное
    задание, но стенд между прогонами копил бы «99+» в колокольчике).

    Нужна двум наборам тестов сразу: авто-выпуск срабатывает всюду, где
    вторая неделя формы в точности повторяет первую.
    """
    await conn.execute(
        "delete from notification_recipients where notification_event_id in "
        "(select ne.id from notification_events ne where ne.entity_type='dataset_release' "
        " and ne.entity_id in (select id from dataset_releases where object_id=$1::uuid))", object_id)
    await conn.execute(
        "delete from notification_events where entity_type='dataset_release' "
        "and entity_id in (select id from dataset_releases where object_id=$1::uuid)", object_id)
    await conn.execute(
        "delete from audit_log where entity_type='dataset_release' "
        "and entity_id in (select id from dataset_releases where object_id=$1::uuid)", object_id)


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
        await purge_release_traces(conn, oid)
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


async def _release(client, headers, job_id, table, code, period, skip=(), supersede=False):
    cols = [c for c in table["columns"] if c["column_index"] > 0]
    body = {
        "table_id": table["id"], "code": code, "name": f"Форма {period}",
        "reporting_period_start": period, "supersede": supersede,
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
