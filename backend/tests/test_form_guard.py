"""Защита от выпуска ЧУЖОЙ формы в объект и от порчи шаблона разметки.

Реальный случай 22.09.2026 на боевом: лист «Перечень услуг» выпустили в объект
формы МАХ и под её кодом. Справочник услуг встал в ряд отчётов МАХ, а шаблон
разметки объекта был молча перезаписан — следующий файл МАХ перестал бы
узнаваться сам.
"""
import io

import pytest

from app import db

from test_layout_template import WEEK1, WEEK2, _form, _release_body, _upload_and_extract, obj  # noqa: F401

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _other_form() -> bytes:
    """Совсем другая таблица: перечень услуг вместо недельной формы."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["№", "Орган, предоставляющий услугу", "Наименование услуги", "Основание", "Примечание"])
    ws.append(["1", "МВД", "Выдача паспорта", "ПП РФ 797", "—"])
    ws.append(["2", "ФНС", "Регистрация ИП", "ПП РФ 797", "—"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _body_for(job: dict, code: str, period: str) -> dict:
    t = job["tables"][0]
    cols = [c for c in t["columns"] if c["column_index"] > 0]
    return {
        "table_id": t["id"], "code": code, "name": f"Перечень {period}",
        "reporting_period_start": period,
        "fields": [{"column_index": c["column_index"], "field_code": f"zfg_c{c['column_index']}",
                    "field_name": f"Графа {c['column_index']}", "data_type": "text",
                    "is_row_label": c["column_index"] == 1} for c in cols],
        "layout": {"data_rect": t["data_rect"], "header_rows": 1, "orientation": "columns",
                   "skip_rows": []},
    }


async def _template(object_id):
    async with db.acquire() as conn:
        return await conn.fetchrow(
            "select fingerprint, dataset_code from object_layout_templates where object_id=$1::uuid",
            object_id)


async def _first_release(client, headers, obj, monkeypatch):  # noqa: F811
    job = await _upload_and_extract(client, headers, obj["folder_id"], _form(WEEK1), "2026-07-22", monkeypatch)
    r = await client.post(f"/extraction-jobs/{job['job_id']}/release", headers=headers,
                          json=_release_body(job, "ztpl_code", "2026-07-22"))
    assert r.status_code == 201, r.text


async def test_other_form_is_stopped_and_nothing_is_written(client, admin_headers, obj, monkeypatch):  # noqa: F811
    await _first_release(client, admin_headers, obj, monkeypatch)
    before = await _template(obj["object_id"])

    job = await _upload_and_extract(client, admin_headers, obj["folder_id"], _other_form(),
                                    "2026-08-12", monkeypatch)
    r = await client.post(f"/extraction-jobs/{job['job_id']}/release", headers=admin_headers,
                          json=_body_for(job, "ztpl_code", "2026-08-12"))
    assert r.status_code == 409, r.text
    d = r.json()["detail"]
    assert d["kind"] == "other_form" and "не похож" in d["message"], d
    async with db.acquire() as conn:
        n = await conn.fetchval("select count(*) from dataset_releases where code='ztpl_code' "
                                "and reporting_period_start='2026-08-12'")
        polluted = await conn.fetchval("select count(*) from canonical_fields where object_id=$1::uuid "
                                       "and code like 'zfg_%'", obj["object_id"])
    assert n == 0, "отказ обязан прийти ДО записи выпуска"
    assert polluted == 0, "в справочнике объекта не должно появиться чужих граф"
    assert await _template(obj["object_id"]) == before


async def test_confirmed_other_form_keeps_the_template(client, admin_headers, obj, monkeypatch):  # noqa: F811
    await _first_release(client, admin_headers, obj, monkeypatch)
    before = await _template(obj["object_id"])
    job = await _upload_and_extract(client, admin_headers, obj["folder_id"], _other_form(),
                                    "2026-08-12", monkeypatch)
    body = {**_body_for(job, "ztpl_code", "2026-08-12"), "confirm_other_form": True}
    r = await client.post(f"/extraction-jobs/{job['job_id']}/release", headers=admin_headers, json=body)
    assert r.status_code == 201, r.text
    assert r.json()["template_kept"] is True
    assert await _template(obj["object_id"]) == before, "шаблон формы объекта затёрт чужой формой"


async def test_other_code_in_same_object_is_stopped(client, admin_headers, obj, monkeypatch):  # noqa: F811
    await _first_release(client, admin_headers, obj, monkeypatch)
    # Другие цифры — иначе файл остановит проверка дубликатов, а не эта.
    job = await _upload_and_extract(client, admin_headers, obj["folder_id"], _form(WEEK2),
                                    "2026-08-19", monkeypatch)
    r = await client.post(f"/extraction-jobs/{job['job_id']}/release", headers=admin_headers,
                          json=_release_body(job, "ztpl_other_code", "2026-08-19"))
    assert r.status_code == 409, r.text
    assert "под кодом «ztpl_code»" in r.json()["detail"]["message"]


async def test_grown_form_passes_and_old_template_can_be_restored(
        client, admin_headers, obj, monkeypatch):  # noqa: F811
    await _first_release(client, admin_headers, obj, monkeypatch)
    before = await _template(obj["object_id"])
    # Форма выросла на графу — это та же форма, и остановки быть не должно.
    job = await _upload_and_extract(client, admin_headers, obj["folder_id"], _form(WEEK1, extra_col=True),
                                    "2026-08-26", monkeypatch)
    t = job["tables"][0]
    names = ["Субъект", "Обращения", "Уведомления", "Записались"]
    codes = ["subject", "obrascheniya", "uvedomleniya", "zapisalis"]
    body = {
        "table_id": t["id"], "code": "ztpl_code", "name": "Форма 2026-08-26",
        "reporting_period_start": "2026-08-26",
        "fields": [{"column_index": i, "field_code": codes[i - 1], "field_name": names[i - 1],
                    "data_type": "text" if i == 1 else "number", "is_row_label": i == 1}
                   for i in range(1, 5)],
        "layout": {"data_rect": t["data_rect"], "header_rows": 2, "orientation": "columns",
                   "skip_rows": [3]},
    }
    r = await client.post(f"/extraction-jobs/{job['job_id']}/release", headers=admin_headers, json=body)
    assert r.status_code == 201, r.text
    after = await _template(obj["object_id"])
    assert after["fingerprint"] != before["fingerprint"]

    h = (await client.get(f"/objects/{obj['object_id']}/layout-templates", headers=admin_headers)).json()
    assert len(h["history"]) == 1 and h["history"][0]["replaced_by"] == "admin"
    r = await client.post(
        f"/objects/{obj['object_id']}/layout-templates/{h['history'][0]['id']}/restore",
        headers=admin_headers)
    assert r.status_code == 200, r.text
    assert (await _template(obj["object_id"]))["fingerprint"] == before["fingerprint"]
    # Вытесненный шаблон не пропал — он теперь в истории.
    assert len(r.json()["history"]) == 1


async def test_move_to_new_object_lets_the_file_be_released_there(
        client, admin_headers, obj, monkeypatch):  # noqa: F811
    await _first_release(client, admin_headers, obj, monkeypatch)
    job = await _upload_and_extract(client, admin_headers, obj["folder_id"], _other_form(),
                                    "2026-08-12", monkeypatch)
    r = await client.post(f"/extraction-jobs/{job['job_id']}/move-to-new-object",
                          headers=admin_headers, json={"name": "ztest_guard_new_obj"})
    assert r.status_code == 201, r.text
    new_obj = r.json()["object_id"]
    try:
        r = await client.post(f"/extraction-jobs/{job['job_id']}/release", headers=admin_headers,
                              json=_body_for(job, "ztest_guard_catalog", "2026-08-12"))
        assert r.status_code == 201, r.text
        async with db.acquire() as conn:
            where = await conn.fetchval(
                "select object_id::text from dataset_releases where code='ztest_guard_catalog'")
        assert where == new_obj
    finally:
        async with db.acquire() as conn:
            await conn.execute("delete from dataset_releases where code='ztest_guard_catalog'")
            await conn.execute("delete from object_layout_templates where object_id=$1::uuid", new_obj)
            await conn.execute("delete from canonical_fields where object_id=$1::uuid", new_obj)
            # Файл возвращаем в папку теста — её уборка удалит его вместе с заданием.
            await conn.execute("update documents set folder_id=$1::uuid where folder_id in "
                               "(select id from folders where object_id=$2::uuid)",
                               obj["folder_id"], new_obj)
            await conn.execute("delete from audit_log where entity_type='object' and entity_id=$1",
                               new_obj)
            await conn.execute("delete from folders where object_id=$1::uuid", new_obj)
            await conn.execute("delete from objects where id=$1::uuid", new_obj)
