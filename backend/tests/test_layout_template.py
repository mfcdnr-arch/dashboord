"""Шаблон разметки объекта: следующий файл той же формы приходит размеченным.

Недельные формы одного объекта — это ОДИН бланк за разные даты. Разметка
(область, этажи шапки, столбец названий, выбранные графы, снятые строки) нигде
не сохранялась, и человек размечал одну и ту же форму заново каждую неделю.

Здесь проверяется главное: разметка переносится, когда структура совпала, и НЕ
переносится, когда форма изменилась, — чужая разметка дала бы неверные цифры на
дашборде без единого признака ошибки.
"""
import io

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

import pytest_asyncio

from app import db
from app.modules.documents import storage
from app.modules.ingestion import mapping, service


def _form(rows: list[tuple], extra_col: bool = False) -> bytes:
    """Недельная форма: две строки шапки, «№ п/п», субъект и показатели."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "МАХ_ход_внедрения"
    top = ["№ п/п", "Субъект", "Обращения", "Уведомления"] + (["Записались"] if extra_col else [])
    ws.append(top)
    ws.append(["1", "2", "3", "4"] + (["5"] if extra_col else []))  # нумерация граф
    for r in rows:
        ws.append(list(r) + ([0] if extra_col else []))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


WEEK1 = [("1", "Донецкая Народная Республика", 891651, 108584), ("2", "", 0, 0)]
WEEK2 = [("1", "Донецкая Народная Республика", 929825, 146758), ("2", "", 0, 0)]


@pytest_asyncio.fixture
async def obj(client, admin_headers):
    r = await client.post("/objects", headers=admin_headers, json={"name": "ztest_tpl_obj"})
    oid = r.json()["id"]
    r = await client.post(f"/objects/{oid}/folders", headers=admin_headers, json={"name": "ztest_tpl_folder"})
    fid = r.json()["id"]
    yield {"object_id": oid, "folder_id": fid}
    async with db.acquire() as conn:
        await conn.execute(
            "delete from dataset_values where dataset_release_id in "
            "(select id from dataset_releases where object_id=$1::uuid)", oid)
        await conn.execute(
            "delete from dataset_release_fields where dataset_release_id in "
            "(select id from dataset_releases where object_id=$1::uuid)", oid)
        await conn.execute("delete from object_layout_templates where object_id=$1::uuid", oid)
        await conn.execute("delete from dataset_releases where object_id=$1::uuid", oid)
        await conn.execute("delete from canonical_fields where object_id=$1::uuid", oid)
        await conn.execute(
            "delete from extraction_jobs where document_version_id in "
            "(select dv.id from document_versions dv join documents d on d.id=dv.document_id "
            " where d.folder_id=$1::uuid)", fid)
        await conn.execute("delete from document_versions where document_id in "
                           "(select id from documents where folder_id=$1::uuid)", fid)
        await conn.execute("delete from documents where folder_id=$1::uuid", fid)
        await conn.execute("delete from folders where id=$1::uuid", fid)
        await conn.execute("delete from objects where id=$1::uuid", oid)


async def _upload_and_extract(client, headers, folder_id, content: bytes, period: str,
                              monkeypatch) -> dict:
    """Файл → распознавание → payload задания (MinIO подменён: его нет в тестах)."""
    monkeypatch.setattr(storage, "put_object", lambda name, data, ct: f"documents/{name}")
    r = await client.post(
        f"/folders/{folder_id}/documents", headers=headers,
        files={"file": (f"forma_{period}.xlsx", content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"reporting_period_start": period})
    assert r.status_code == 201, r.text
    version_id = r.json()["version_id"]

    monkeypatch.setattr(storage, "get_object", lambda path: content)
    async with db.acquire() as conn:
        job_id = await service.enqueue_or_run(conn, version_id)
    await service.run_extraction(job_id)

    r = await client.get(f"/extraction-jobs/{job_id}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _release_body(job: dict, code: str, period: str) -> dict:
    """Разметка «как руками»: снимаем «№ п/п» и пустую строку-заготовку."""
    t = job["tables"][0]
    cols = [c for c in t["columns"] if c["column_index"] > 0]
    return {
        "table_id": t["id"], "code": code, "name": f"Форма {period}",
        "reporting_period_start": period,
        "fields": [{
            "column_index": c["column_index"],
            "field_code": ["subject", "obrascheniya", "uvedomleniya"][c["column_index"] - 1],
            "field_name": ["Субъект", "Обращения", "Уведомления"][c["column_index"] - 1],
            "data_type": "text" if c["column_index"] == 1 else "number",
            "is_row_label": c["column_index"] == 1,
        } for c in cols],
        "layout": {"data_rect": t["data_rect"] or [0, 0, 3, 3], "header_rows": 2,
                   "orientation": "columns", "skip_rows": [3]},
    }


async def test_template_is_reused_by_next_file_of_same_form(
        client, admin_headers, obj, monkeypatch):
    """Вторая неделя той же формы открывается уже размеченной."""
    job1 = await _upload_and_extract(
        client, admin_headers, obj["folder_id"], _form(WEEK1), "2026-07-22", monkeypatch)
    assert job1["layout_template"] is None, "до первого выпуска шаблона быть не может"

    body = _release_body(job1, "ztpl_code", "2026-07-22")
    r = await client.post(f"/extraction-jobs/{job1['job_id']}/release", headers=admin_headers, json=body)
    assert r.status_code == 201, r.text

    # Вторая неделя: тот же бланк, другие цифры.
    job2 = await _upload_and_extract(
        client, admin_headers, obj["folder_id"], _form(WEEK2), "2026-07-29", monkeypatch)
    tpl = job2["layout_template"]
    assert tpl is not None and tpl["match"] == "exact", tpl
    assert tpl["table_id"] == job2["tables"][0]["id"]
    assert tpl["layout"]["header_rows"] == 2
    assert tpl["layout"]["orientation"] == "columns"
    # Снятая строка-заготовка перенеслась: строк столько же.
    assert tpl["layout"]["skip_rows"] == [3]
    assert tpl["rows_differ"] is False
    # Показатели — те, что человек оставил и переименовал; «№ п/п» среди них нет.
    codes = {f["field_code"] for f in tpl["fields"]}
    assert codes == {"subject", "obrascheniya", "uvedomleniya"}
    assert any(f["is_row_label"] and f["field_code"] == "subject" for f in tpl["fields"])
    assert tpl["dataset_code"] == "ztpl_code"

    # Разметка, подставленная шаблоном, даёт тот же выпуск, что и ручная.
    body2 = _release_body(job2, "ztpl_code", "2026-07-29")
    body2["layout"] = tpl["layout"]
    body2["fields"] = tpl["fields"]
    r = await client.post(f"/extraction-jobs/{job2['job_id']}/release", headers=admin_headers, json=body2)
    assert r.status_code == 201, r.text
    assert r.json()["rows"] == 1, "строка-заготовка должна остаться исключённой"


async def test_template_not_applied_when_form_changed(client, admin_headers, obj, monkeypatch):
    """Появилась новая графа — разметка НЕ подставляется, человек размечает сам."""
    job1 = await _upload_and_extract(
        client, admin_headers, obj["folder_id"], _form(WEEK1), "2026-07-22", monkeypatch)
    r = await client.post(f"/extraction-jobs/{job1['job_id']}/release", headers=admin_headers,
                          json=_release_body(job1, "ztpl_code", "2026-07-22"))
    assert r.status_code == 201, r.text

    job2 = await _upload_and_extract(
        client, admin_headers, obj["folder_id"], _form(WEEK2, extra_col=True), "2026-08-05", monkeypatch)
    tpl = job2["layout_template"]
    assert tpl is not None, "шаблон объекта должен быть виден человеку"
    assert tpl["match"] == "structure_differs"
    assert tpl["table_id"] is None, "применять шаблон к изменившейся форме нельзя"


async def test_row_count_change_drops_skipped_rows(client, admin_headers, obj, monkeypatch):
    """Строк стало больше — снятые строки не переносятся: они позиционные.

    Иначе исключение «строка 4» выбросило бы данные нового субъекта, который
    встал на её место, и показатель молча просел бы.
    """
    job1 = await _upload_and_extract(
        client, admin_headers, obj["folder_id"], _form(WEEK1), "2026-07-22", monkeypatch)
    r = await client.post(f"/extraction-jobs/{job1['job_id']}/release", headers=admin_headers,
                          json=_release_body(job1, "ztpl_code", "2026-07-22"))
    assert r.status_code == 201, r.text

    grown = WEEK2 + [("3", "Мариуполь", 12345, 678)]
    job2 = await _upload_and_extract(
        client, admin_headers, obj["folder_id"], _form(grown), "2026-08-05", monkeypatch)
    tpl = job2["layout_template"]
    assert tpl["match"] == "exact", "состав граф не менялся — форма та же"
    assert tpl["rows_differ"] is True
    assert tpl["layout"]["skip_rows"] == []
    # Область расширена до последней заполненной строки — новый субъект не отрезан.
    assert tpl["layout"]["data_rect"][2] >= 4


async def test_fingerprint_ignores_values_but_sees_headers():
    """Отпечаток структуры: цифры не влияют, заголовки влияют."""
    area = [["Субъект", "Обращения"], ["ДНР", "100"]]
    same_values_changed = [["Субъект", "Обращения"], ["ДНР", "999"]]
    renamed = [["Субъект", "Обращения граждан"], ["ДНР", "100"]]
    assert mapping.structure_fingerprint(area, 1) == mapping.structure_fingerprint(same_values_changed, 1)
    assert mapping.structure_fingerprint(area, 1) != mapping.structure_fingerprint(renamed, 1)
    # Число этажей шапки — часть структуры: при другой шапке имена показателей иные.
    assert mapping.structure_fingerprint(area, 1) != mapping.structure_fingerprint(area, 2)
