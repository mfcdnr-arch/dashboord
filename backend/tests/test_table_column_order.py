"""Таблица показывает графы в порядке исходного листа (08.10.2026).

До этого столбцы шли по алфавиту КОДОВ: у формы Минэкономразвития
«Дата/время/место» вставала первой, а «Краткая характеристика» уезжала от
своего «Наименования» — сверить таблицу на дашборде с файлом было нельзя.
Коды здесь намеренно выбраны так, что алфавит и порядок листа противоположны:
иначе тест прошёл бы и при прежней сортировке.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app.modules.ingestion import service  # noqa: E402

from pipeline_helpers import (  # noqa: E402,F401 — фикстуры подключаются импортом
    WEEK1, _form, _upload, folder, offline_queue,
)

CODE = "ztest_colorder"
# Лист: «Субъект» | «Обращения» | «Уведомления». Коды — наоборот по алфавиту.
CODES = {1: ("zz_subject", "Субъект", "text"), 2: ("mm_obr", "Обращения", "number"),
         3: ("aa_uved", "Уведомления", "number")}


async def _released(client, headers, folder, monkeypatch):
    up = await _upload(client, headers, folder["folder_id"], _form(WEEK1), "2026-07-22", monkeypatch)
    await service.run_extraction(up["extraction_job_id"])
    job = (await client.get(f"/extraction-jobs/{up['extraction_job_id']}", headers=headers)).json()
    table = job["tables"][0]
    body = {
        "table_id": table["id"], "code": CODE, "name": "Форма", "reporting_period_start": "2026-07-22",
        "fields": [{
            "column_index": c["column_index"], "field_code": CODES[c["column_index"]][0],
            "field_name": CODES[c["column_index"]][1], "data_type": CODES[c["column_index"]][2],
            "is_row_label": False,
        } for c in table["columns"] if c["column_index"] in CODES],
        "layout": {"data_rect": table["data_rect"] or [0, 0, 2, 3], "header_rows": 2,
                   "orientation": "columns", "skip_rows": []},
    }
    r = await client.post(f"/extraction-jobs/{job['job_id']}/release", headers=headers, json=body)
    assert r.status_code == 201, r.text


async def _columns(client, headers, cfg):
    r = await client.post("/widgets/preview", headers=headers, json={
        "widget_type": "table", "name": "T", "config": {"dataset_code": CODE, **cfg}})
    assert r.status_code == 200, r.text
    return r.json()["columns"]


async def test_table_columns_follow_the_sheet(client, admin_headers, folder, monkeypatch, offline_queue):
    # Выпуск и всё вокруг него убирает фикстура `folder`.
    await _released(client, admin_headers, folder, monkeypatch)
    cols = await _columns(client, admin_headers, {})
    assert cols == ["zz_subject", "mm_obr", "aa_uved"], (
        f"столбцы должны идти как в листе, а пришло {cols} — похоже, снова по алфавиту кодов")
    # Выбранные человеком графы — тоже в порядке листа, а не в порядке щелчков:
    # иначе одна и та же таблица выглядела бы по-разному у двух авторов.
    cols = await _columns(client, admin_headers, {"value_fields": ["aa_uved", "zz_subject"]})
    assert cols == ["zz_subject", "aa_uved"]
