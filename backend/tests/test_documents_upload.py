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


def _xlsx(value: int = 1) -> bytes:
    """Мини-форма. `value` меняет цифру — так недельные отчёты отличаются друг
    от друга, как в жизни. Побайтово одинаковые файлы система теперь считает
    дублями (п. 7), и тест, который шлёт один и тот же файл несколько раз,
    проверял бы уже не то, ради чего написан."""
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.append(["Услуга", "Факт"])
    wb.active.append(["Тест", value])
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
    # Содержимое привязано к имени: два вызова подряд не должны выглядеть
    # дублями (проверка п. 7), иначе тесты удаления упрутся в 409.
    r = await client.post(
        f"/folders/{folder}/documents", headers=admin_headers,
        files={"file": (name, _xlsx(abs(hash(name + period)) % 100000),
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


async def test_superadmin_can_delete_document_with_its_data(
        client, admin_headers, superadmin_headers, folder, fake_storage, fake_remove, ids):
    """Выход из тупика: раньше документ с выпущенными данными оставался в
    системе НАВСЕГДА — удаления выпуска в системе нет вовсе. Теперь
    суперадминистратор может снести документ вместе с его данными."""
    doc = await _upload(client, admin_headers, folder, name="withdata.xlsx", period="2026-06-01")
    async with db.acquire() as conn:
        rel = await conn.fetchval(
            "insert into dataset_releases(organization_id, code, name, source_document_version_id, "
            "reporting_period_start, created_by) values($1,'ztest_ds_wd','Тест',$2::uuid,'2026-06-01',$3) "
            "returning id", ids["org"], doc["version_id"], ids["admin"])
        await conn.execute(
            "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
            "values($1,0,'Строка','f',1)", rel)
    try:
        # обычный admin так не может — операция необратима
        r = await client.delete(f"/folders/{folder}/documents/{doc['id']}?with_data=true", headers=admin_headers)
        assert r.status_code == 403, r.text

        r = await client.delete(f"/folders/{folder}/documents/{doc['id']}?with_data=true",
                                headers=superadmin_headers)
        assert r.status_code == 204, r.text
        async with db.acquire() as conn:
            assert await conn.fetchval("select count(*) from documents where id=$1::uuid", doc["id"]) == 0
            assert await conn.fetchval("select count(*) from dataset_releases where code='ztest_ds_wd'") == 0
            assert await conn.fetchval(
                "select count(*) from dataset_values where dataset_release_id=$1", rel) == 0, \
                "значения выпуска должны уйти каскадом"
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from dataset_releases where code='ztest_ds_wd'")


async def test_delete_with_data_blocked_while_widget_uses_dataset(
        client, admin_headers, superadmin_headers, folder, fake_storage, fake_remove, ids):
    """Если после удаления у кода не осталось бы ни одного выпуска, а на него
    ссылается виджет — отказываем и называем виновника."""
    doc = await _upload(client, admin_headers, folder, name="used.xlsx", period="2026-06-08")
    did = None
    async with db.acquire() as conn:
        await conn.execute(
            "insert into dataset_releases(organization_id, code, name, source_document_version_id, "
            "reporting_period_start, created_by) values($1,'ztest_ds_used','Тест',$2::uuid,'2026-06-08',$3)",
            ids["org"], doc["version_id"], ids["admin"])
    try:
        did = (await client.post("/dashboards", headers=admin_headers,
                                 json={"name": "ztest_doc_dash"})).json()["id"]
        pid = (await client.post(f"/dashboards/{did}/pages", headers=admin_headers,
                                 json={"name": "Стр"})).json()["id"]
        await client.post(f"/dashboard-pages/{pid}/widgets", headers=admin_headers,
                          json={"name": "Карточка", "widget_type": "kpi",
                                "config": {"dataset_code": "ztest_ds_used", "value_field": "f"}})

        r = await client.delete(f"/folders/{folder}/documents/{doc['id']}?with_data=true",
                                headers=superadmin_headers)
        assert r.status_code == 409, r.text
        assert "Карточка" in r.text and "ztest_doc_dash" in r.text
    finally:
        if did:
            from conftest import purge_dashboard
            await purge_dashboard(did)
        async with db.acquire() as conn:
            await conn.execute("delete from dataset_releases where code='ztest_ds_used'")


async def test_delete_document_requires_manage_role(
        client, admin_headers, folder, fake_storage, viewer):
    doc = await _upload(client, admin_headers, folder, name="perm.xlsx", period="2026-05-01")
    r = await client.delete(f"/folders/{folder}/documents/{doc['id']}", headers=viewer["headers"])
    assert r.status_code == 403
    async with db.acquire() as conn:
        assert await conn.fetchval("select count(*) from documents where id=$1::uuid", doc["id"]) == 1


async def test_documents_are_listed_by_reporting_date(client, admin_headers, folder, fake_storage):
    """Список папки идёт по ОТЧЁТНОЙ дате, а не по времени загрузки.

    Заказчик грузит недельные формы вразнобой (сначала августовскую, потом
    апрельскую), и список выглядел вперемешку — по нему нельзя было понять
    хронологию. Загружаем намеренно не по порядку и ждём убывание дат.
    """
    upload_order = ["2026-04-15", "2026-08-05", "2026-06-10", "2026-07-22"]
    for n, d in enumerate(upload_order):
        r = await client.post(
            f"/folders/{folder}/documents",
            headers=admin_headers,
            files={"file": (f"Показатели MAX {d}.xlsx", _xlsx(100 + n),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"reporting_period_start": d},
        )
        assert r.status_code in (200, 201), r.text

    items = (await client.get(f"/folders/{folder}/documents", headers=admin_headers)).json()["items"]
    dates = [str(i["reporting_period_start"]) for i in items]
    assert dates == sorted(dates, reverse=True), dates
    assert dates[0].startswith("2026-08-05"), "самый свежий отчёт должен быть первым"


async def test_new_document_lands_in_its_place_by_date(client, admin_headers, folder, fake_storage):
    """Файл, добавленный позже всех, встаёт на своё место по отчётной дате.

    Это сценарий заказчика: недельные формы догружаются задним числом, и новый
    файл должен оказаться между соседними по дате, а не в конце списка.
    """
    async def upload(d: str):
        r = await client.post(
            f"/folders/{folder}/documents", headers=admin_headers,
            files={"file": (f"Показатели MAX {d}.xlsx", _xlsx(int(d[5:7]) * 100 + int(d[8:10])),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"reporting_period_start": d},
        )
        assert r.status_code in (200, 201), r.text

    for d in ("2026-04-01", "2026-06-10", "2026-08-05"):
        await upload(d)
    await upload("2026-05-20")  # добавлен последним, а по дате — второй с конца

    items = (await client.get(f"/folders/{folder}/documents", headers=admin_headers)).json()["items"]
    dates = [str(i["reporting_period_start"]) for i in items]
    assert dates == ["2026-08-05", "2026-06-10", "2026-05-20", "2026-04-01"], dates


# --- Дубли файлов (п. 7 списка заказчика) ---------------------------------- #
# Контрольная сумма считалась с самого начала, но никогда не проверялась: один и
# тот же отчёт можно было залить дважды молча, а потом дважды выпустить из него
# данные за один период. Проверка — предупреждение, а не запрет: решение за
# человеком, но принятое осознанно.
XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


async def test_identical_file_is_flagged_as_duplicate(client, admin_headers, folder, fake_storage):
    content = _xlsx()
    r = await client.post(
        f"/folders/{folder}/documents", headers=admin_headers,
        files={"file": ("nedelya.xlsx", content, XLSX_MEDIA)},
        data={"reporting_period_start": "2026-03-01"})
    assert r.status_code == 201, r.text

    # Тот же файл, другое имя и другой отчётный период — всё равно дубль:
    # сравнивается содержимое, а не подпись на нём.
    r = await client.post(
        f"/folders/{folder}/documents", headers=admin_headers,
        files={"file": ("kopiya.xlsx", content, XLSX_MEDIA)},
        data={"reporting_period_start": "2026-03-08"})
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert "уже загружен" in detail["message"]
    assert detail["duplicate"]["filename"] == "nedelya.xlsx", "нужно назвать, ЧТО именно совпало"

    # Второй файл не создан: отказ не должен оставлять следов.
    async with db.acquire() as conn:
        cnt = await conn.fetchval("select count(*) from documents where folder_id=$1::uuid", folder)
    assert cnt == 1

    # …но человек может настоять — тогда загрузка проходит.
    r = await client.post(
        f"/folders/{folder}/documents", headers=admin_headers,
        files={"file": ("kopiya.xlsx", content, XLSX_MEDIA)},
        data={"reporting_period_start": "2026-03-08", "force": "true"})
    assert r.status_code == 201, r.text
    async with db.acquire() as conn:
        cnt = await conn.fetchval("select count(*) from documents where folder_id=$1::uuid", folder)
    assert cnt == 2


async def test_different_content_is_not_a_duplicate(client, admin_headers, folder, fake_storage):
    """Отчёт следующей недели отличается цифрами — он обязан проходить молча."""
    from openpyxl import Workbook

    def sheet(value):
        wb = Workbook()
        wb.active.append(["Услуга", "Факт"])
        wb.active.append(["Тест", value])
        import io as _io
        buf = _io.BytesIO(); wb.save(buf); return buf.getvalue()

    for i, period in enumerate(("2026-04-01", "2026-04-08")):
        r = await client.post(
            f"/folders/{folder}/documents", headers=admin_headers,
            files={"file": (f"w{i}.xlsx", sheet(100 + i), XLSX_MEDIA)},
            data={"reporting_period_start": period})
        assert r.status_code == 201, r.text
