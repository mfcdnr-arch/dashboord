"""Датасет — это РЯД отчётов одной формы, а не один файл.

Замечание заказчика: «при создании дашборда, при выборе датасета
предполагается только один файл». Так и выглядело: каталог источников
подписывал набор данных именем самого свежего документа, и человек решал, что
виджет посчитает по нему одному — а под кодом лежат все недельные отчёты
(у заказчика два, раньше было пятнадцать). Отсюда же непонимание, откуда на
графике «Динамика» берутся точки.

Сами данные всегда считались правильно (карточка — по активному выпуску,
динамика — по всем), неверной была ПОДПИСЬ. Тест держит именно её: справочник
обязан отдавать все файлы кода и их число.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db


async def test_dataset_reports_all_its_documents(client, admin_headers, ids):
    """Два отчёта одной формы под одним кодом — справочник показывает оба."""
    async with db.acquire() as conn:
        await _drop(conn)
        oid = await conn.fetchval(
            "insert into objects(organization_id,name) values($1,'ztest_src_obj') returning id", ids["org"])
        fid = await conn.fetchval(
            "insert into folders(organization_id,object_id,name) values($1,$2,'ztest_src_folder') returning id",
            ids["org"], oid)
        await conn.execute(
            "insert into canonical_fields(object_id, code, name, data_type) "
            "values($1,'plan','План','number') on conflict do nothing", oid)
        for i, day in enumerate(("2026-05-04", "2026-05-11")):
            doc = await conn.fetchval(
                "insert into documents(organization_id, folder_id, original_filename, source_type, "
                "reporting_period_start, uploaded_by) values($1,$2,$3,'xlsx',$4::text::date,$5) returning id",
                ids["org"], fid, f"ztest_src_{day}.xlsx", day, ids["admin"])
            ver = await conn.fetchval(
                "insert into document_versions(document_id, version_no, storage_path, checksum, "
                "file_size_bytes, uploaded_by) values($1,1,$2,$3,10,$4) returning id",
                doc, f"documents/ztest_src_{i}", f"ztest_src_sum_{i}", ids["admin"])
            rel = await conn.fetchval(
                "insert into dataset_releases(organization_id, code, name, status, reporting_period_start, "
                "created_by, object_id, source_document_version_id) "
                "values($1,'ztest_src_ds','Недельная форма','released',$2::text::date,$3,$4,$5) returning id",
                ids["org"], day, ids["admin"], oid, ver)
            await conn.execute(
                "insert into dataset_release_fields(dataset_release_id, canonical_field_code) values($1,'plan')", rel)
            await conn.execute(
                "insert into dataset_values(dataset_release_id,row_index,row_label,canonical_field_code,value_number) "
                "values($1,0,'Итого','plan',$2)", rel, 100 + i)
    try:
        r = await client.get("/metrics/data-sources", headers=admin_headers)
        assert r.status_code == 200, r.text
        ds = next(d for d in r.json()["datasets"] if d["code"] == "ztest_src_ds")

        assert ds["releases"] == 2, "за кодом стоят ОБА отчёта, а не один файл"
        assert len(ds["documents"]) == 2, f"должны быть названы оба файла: {ds['documents']}"
        assert sorted(ds["dates"]) == ["2026-05-04", "2026-05-11"]

        # `document` остаётся файлом ПОСЛЕДНЕГО отчёта: именно по нему считают
        # карточки и таблицы, и это тоже надо уметь показать.
        assert ds["document"] == "ztest_src_2026-05-11.xlsx"
    finally:
        async with db.acquire() as conn:
            await _drop(conn)


async def _drop(conn):
    await conn.execute("delete from dataset_values where dataset_release_id in "
                       "(select id from dataset_releases where code='ztest_src_ds')")
    await conn.execute("delete from dataset_release_fields where dataset_release_id in "
                       "(select id from dataset_releases where code='ztest_src_ds')")
    await conn.execute("delete from dataset_releases where code='ztest_src_ds'")
    await conn.execute("delete from document_versions where document_id in "
                       "(select id from documents where original_filename like 'ztest_src_%')")
    await conn.execute("delete from documents where original_filename like 'ztest_src_%'")
    await conn.execute("delete from folders where name='ztest_src_folder'")
    await conn.execute("delete from canonical_fields where object_id in "
                       "(select id from objects where name='ztest_src_obj')")
    await conn.execute("delete from objects where name='ztest_src_obj'")
