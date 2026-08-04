"""Загрузка документов: санитайз имени файла и целостность при сбое хранилища.

Регрессия (финальный аудит): имя файла из запроса подставлялось в ключ объекта
MinIO как есть. Файл с «../» в имени → minio-py отвергал ключ, обработчик падал
с сырым 500, а строка `documents` к этому моменту УЖЕ была вставлена — в папке
оставался «документ без версии»: он виден в списке, но его нельзя ни скачать,
ни отправить на распознавание.

MinIO в тестовом окружении не поднимается (см. conftest), поэтому запись в
хранилище подменяется заглушкой — проверяется именно логика роутера.
"""
import io

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

import pytest_asyncio

from app import db
from app.modules.documents import storage


def _xlsx() -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.append(["Услуга", "Факт"])
    wb.active.append(["Тест", 1])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest_asyncio.fixture
async def folder(client, admin_headers):
    r = await client.post("/objects", headers=admin_headers, json={"name": "ztest_docs_obj"})
    oid = r.json()["id"]
    r = await client.post(f"/objects/{oid}/folders", headers=admin_headers, json={"name": "ztest_docs_folder"})
    fid = r.json()["id"]
    yield fid
    async with db.acquire() as conn:
        await conn.execute("delete from document_versions where document_id in "
                           "(select id from documents where folder_id=$1::uuid)", fid)
        await conn.execute("delete from documents where folder_id=$1::uuid", fid)
        await conn.execute("delete from folders where id=$1::uuid", fid)
        await conn.execute("delete from objects where id=$1::uuid", oid)


@pytest.fixture
def fake_storage(monkeypatch):
    """Подменяет запись в MinIO; собирает ключи объектов."""
    keys: list[str] = []

    def put_object(object_name, data, content_type):
        keys.append(object_name)
        return f"documents/{object_name}"

    monkeypatch.setattr(storage, "put_object", put_object)
    return keys


async def test_filename_with_path_segments_is_sanitized(client, admin_headers, folder, fake_storage):
    r = await client.post(
        f"/folders/{folder}/documents", headers=admin_headers,
        files={"file": ("../../../evil.xlsx", _xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"reporting_period_start": "2026-01-01"})
    assert r.status_code == 201, r.text
    assert r.json()["original_filename"] == "evil.xlsx"
    assert ".." not in r.json()["storage_path"]
    assert fake_storage and ".." not in fake_storage[0]


async def test_storage_failure_leaves_no_orphan_document(client, admin_headers, folder, monkeypatch):
    """Сбой записи в хранилище → 502 и НИ ОДНОЙ строки documents без версии."""
    def boom(object_name, data, content_type):
        raise ValueError("object name with '.' or '..' path segment is not supported")

    monkeypatch.setattr(storage, "put_object", boom)
    r = await client.post(
        f"/folders/{folder}/documents", headers=admin_headers,
        files={"file": ("broken.xlsx", _xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"reporting_period_start": "2026-02-01"})
    assert r.status_code == 502, r.text
    async with db.acquire() as conn:
        orphans = await conn.fetchval(
            "select count(*) from documents d where d.folder_id=$1::uuid "
            "and not exists (select 1 from document_versions v where v.document_id=d.id)", folder)
    assert orphans == 0
