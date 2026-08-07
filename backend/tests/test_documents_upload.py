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


@pytest.fixture
def fake_remove(monkeypatch):
    """Подменяет удаление объекта в MinIO; собирает удалённые storage_path."""
    removed: list[str] = []
    monkeypatch.setattr(storage, "remove_object", lambda path: removed.append(path))
    return removed


async def _upload(client, admin_headers, folder, name="del.xlsx", period="2026-03-01"):
    r = await client.post(
        f"/folders/{folder}/documents", headers=admin_headers,
        files={"file": (name, _xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"reporting_period_start": period})
    assert r.status_code == 201, r.text
    return r.json()


async def test_delete_document_removes_versions_and_files(
        client, admin_headers, folder, fake_storage, fake_remove):
    doc = await _upload(client, admin_headers, folder)

    r = await client.delete(f"/folders/{folder}/documents/{doc['id']}", headers=admin_headers)
    assert r.status_code == 204, r.text
    # Повторное удаление и удаление через чужую папку — 404, существование не палим.
    assert (await client.delete(f"/folders/{folder}/documents/{doc['id']}",
                                headers=admin_headers)).status_code == 404

    async with db.acquire() as conn:
        assert await conn.fetchval("select count(*) from documents where id=$1::uuid", doc["id"]) == 0
        # версии ушли каскадом
        assert await conn.fetchval(
            "select count(*) from document_versions where document_id=$1::uuid", doc["id"]) == 0
        act = await conn.fetchval(
            "select action::text from audit_log where entity_type='document' and entity_id=$1::uuid",
            doc["id"])
    assert act == "delete"
    # файл версии удалён из хранилища
    assert fake_remove == [doc["storage_path"]]


async def test_delete_document_blocked_when_dataset_released(
        client, admin_headers, folder, fake_storage, fake_remove, ids):
    """Из документа выпустили данные → удаление отклоняется, файл не трогаем.

    `dataset_releases.source_document_version_id` — это происхождение цифр на
    дашборде: удалив документ, мы оборвали бы связь «показатель → первичный файл».
    """
    doc = await _upload(client, admin_headers, folder, name="released.xlsx", period="2026-04-01")
    async with db.acquire() as conn:
        await conn.execute(
            "insert into dataset_releases(organization_id, code, name, source_document_version_id, "
            "reporting_period_start, created_by) values($1,'ztest_ds_del','Тест',$2::uuid,'2026-04-01',$3)",
            ids["org"], doc["version_id"], ids["admin"])
    try:
        r = await client.delete(f"/folders/{folder}/documents/{doc['id']}", headers=admin_headers)
        assert r.status_code == 409, r.text
        assert "выпусков: 1" in r.json()["detail"]
        assert fake_remove == []
        async with db.acquire() as conn:
            assert await conn.fetchval("select count(*) from documents where id=$1::uuid", doc["id"]) == 1
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from dataset_releases where code='ztest_ds_del'")


async def test_delete_document_requires_manage_role(
        client, admin_headers, folder, fake_storage, viewer):
    doc = await _upload(client, admin_headers, folder, name="perm.xlsx", period="2026-05-01")
    r = await client.delete(f"/folders/{folder}/documents/{doc['id']}", headers=viewer["headers"])
    assert r.status_code == 403
    async with db.acquire() as conn:
        assert await conn.fetchval("select count(*) from documents where id=$1::uuid", doc["id"]) == 1
