"""Проверки качества данных: сверка готовящегося выпуска с прошлой неделей.

Главный случай — настоящий, из практики заказчика (05.08.2026): строка
«Донецкая Народная Республика» в новом отчёте совпала с отчётом за 29.07
посимвольно. Данные неделю не обновляли, система приняла их молча, и на
дашборде они выглядели свежими. Заметить такое по одному файлу нельзя —
только сравнением с предыдущим выпуском.

Проверки НЕ блокируют выпуск (решение за человеком, выпуск обратим), поэтому
тесты требуют именно предупреждений, а не отказов.
"""
import pytest

from app.modules.ingestion import quality

NAMES = {
    "obr_total": "Количество обращений · Факт · нарастающим итогом",
    "obr_week": "Количество обращений · Факт · за отчётную неделю",
    "uved_total": "Количество уведомлений · Факт · нарастающим итогом",
}


def test_row_copied_from_previous_week_is_flagged():
    """Строка не изменилась за неделю — самый дорогой случай, ловим его."""
    prev = {("ДНР", "obr_total"): 891651.0, ("ДНР", "uved_total"): 108584.0,
            ("Мариуполь", "obr_total"): 1000.0, ("Мариуполь", "uved_total"): 500.0}
    cur = {("ДНР", "obr_total"): 891651.0, ("ДНР", "uved_total"): 108584.0,   # не обновили
           ("Мариуполь", "obr_total"): 1200.0, ("Мариуполь", "uved_total"): 600.0}

    w = quality.compare_with_previous(cur, prev, NAMES, "29.07.2026")
    same = [x for x in w if x["code"] == "same_as_previous"]
    assert same, w
    assert "ДНР" in same[0]["message"]
    assert "Мариуполь" not in same[0]["message"], "изменившаяся строка не должна попадать в замечание"
    assert "29.07.2026" in same[0]["message"]


def test_all_rows_identical_says_so_plainly():
    prev = {("ДНР", "obr_total"): 100.0}
    w = quality.compare_with_previous(dict(prev), prev, NAMES, "29.07.2026")
    assert any("Все данные совпадают" in x["message"] for x in w), w


def test_cumulative_total_cannot_decrease():
    """Накопительный итог уменьшился — либо ошибка в форме, либо не тот показатель."""
    prev = {("ДНР", "obr_total"): 891651.0}
    cur = {("ДНР", "obr_total"): 800000.0}
    w = quality.compare_with_previous(cur, prev, NAMES, "29.07.2026")
    drop = [x for x in w if x["code"] == "cumulative_drop"]
    assert drop, w
    assert "891 651" in drop[0]["message"] and "800 000" in drop[0]["message"]


def test_weekly_slice_not_flagged_when_it_drops():
    """Значение ЗА НЕДЕЛЮ падать может — это срез, а не накопление."""
    prev = {("ДНР", "obr_week"): 50000.0, ("ДНР", "obr_total"): 891651.0}
    cur = {("ДНР", "obr_week"): 30000.0, ("ДНР", "obr_total"): 929825.0}
    w = quality.compare_with_previous(cur, prev, NAMES, "29.07.2026")
    assert not [x for x in w if x["code"] == "cumulative_drop"], w


def test_weekly_cannot_exceed_cumulative():
    """За неделю больше, чем накопленным итогом — графы перепутаны местами."""
    prev = {("ДНР", "obr_total"): 100.0}
    cur = {("ДНР", "obr_total"): 1000.0, ("ДНР", "obr_week"): 5000.0}
    w = quality.compare_with_previous(cur, prev, NAMES, "29.07.2026")
    over = [x for x in w if x["code"] == "weekly_over_total"]
    assert over, w
    assert "5 000" in over[0]["message"]


def test_first_release_has_nothing_to_compare_with():
    assert quality.compare_with_previous({("ДНР", "obr_total"): 1.0}, {}, NAMES, None) == []


def test_slice_classification():
    assert quality.classify_slice(NAMES["obr_total"]) == "cumulative"
    assert quality.classify_slice(NAMES["obr_week"]) == "weekly"
    # Месячный накопительный итог законно падает при смене месяца — не сравниваем.
    assert quality.classify_slice("Обращения · Факт · нарастающим итогом (текущий месяц)") == "other"


def test_values_from_rows_takes_only_numeric_fields():
    fields = [
        {"column_index": 0, "field_code": "subj", "field_name": "Субъект", "data_type": "text", "is_row_label": True},
        {"column_index": 1, "field_code": "obr_total", "field_name": NAMES["obr_total"], "data_type": "number"},
        {"column_index": 2, "field_code": "note", "field_name": "Примечание", "data_type": "text"},
    ]
    got = quality.values_from_rows([["ДНР", "1 234", "текст"]], fields, 0)
    assert got == {("ДНР", "obr_total"): 1234.0}


@pytest.mark.asyncio(loop_scope="session")
async def test_quality_check_endpoint_sees_copied_week(client, admin_headers, monkeypatch):
    """Сквозной путь: тот же файл за новую неделю → замечание ДО выпуска."""
    import io

    from app import db
    from app.modules.documents import storage
    from app.modules.ingestion import service

    def _xlsx(value: int) -> bytes:
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active
        ws.append(["Субъект", "Количество обращений · Факт · нарастающим итогом"])
        ws.append(["ДНР", value])
        buf = io.BytesIO(); wb.save(buf); return buf.getvalue()

    r = await client.post("/objects", headers=admin_headers, json={"name": "ztest_qual_obj"})
    oid = r.json()["id"]
    r = await client.post(f"/objects/{oid}/folders", headers=admin_headers, json={"name": "ztest_qual_folder"})
    fid = r.json()["id"]

    async def upload(content, period):
        monkeypatch.setattr(storage, "put_object", lambda n, d, c: f"documents/{n}")
        monkeypatch.setattr(storage, "get_object", lambda p: content)
        # force=true: в этом сценарии тот же файл заливается за новую неделю
        # НАМЕРЕННО — проверяется сверка строк с прошлым выпуском. Побайтовый
        # дубль ловится раньше (п. 7) и требует подтверждения человека; две
        # защиты дополняют друг друга, поэтому здесь подтверждение выдаём сразу.
        rr = await client.post(
            f"/folders/{fid}/documents", headers=admin_headers,
            files={"file": (f"q_{period}.xlsx", content,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"reporting_period_start": period, "force": "true"})
        job_id = rr.json()["extraction_job_id"]
        await service.run_extraction(job_id)
        return (await client.get(f"/extraction-jobs/{job_id}", headers=admin_headers)).json()

    def body(job, period):
        t = job["tables"][0]
        return {
            "table_id": t["id"], "code": "zqual_code", "name": f"Форма {period}",
            "reporting_period_start": period,
            "fields": [
                {"column_index": 0, "field_code": "subj", "field_name": "Субъект",
                 "data_type": "text", "is_row_label": True},
                {"column_index": 1, "field_code": "obr_total",
                 "field_name": "Количество обращений · Факт · нарастающим итогом",
                 "data_type": "number", "is_row_label": False},
            ],
            "layout": {"data_rect": [0, 0, 1, 1], "header_rows": 1,
                       "orientation": "columns", "skip_rows": []},
        }

    try:
        job1 = await upload(_xlsx(891651), "2026-07-22")
        r = await client.post(f"/extraction-jobs/{job1['job_id']}/release",
                              headers=admin_headers, json=body(job1, "2026-07-22"))
        assert r.status_code == 201, r.text

        # Та же цифра за следующую неделю — данные не обновили.
        job2 = await upload(_xlsx(891651), "2026-07-29")
        r = await client.post(f"/extraction-jobs/{job2['job_id']}/quality-check",
                              headers=admin_headers, json=body(job2, "2026-07-29"))
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is False
        assert any(w["code"] == "same_as_previous" for w in r.json()["warnings"]), r.json()

        # То же замечание приезжает и в результате выпуска — расхождения быть не может.
        r = await client.post(f"/extraction-jobs/{job2['job_id']}/release",
                              headers=admin_headers, json=body(job2, "2026-07-29"))
        assert r.status_code == 201, r.text
        assert any(w["code"] == "same_as_previous" for w in r.json()["validation"]["warnings"])
    finally:
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
