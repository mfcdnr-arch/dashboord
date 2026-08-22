"""Общая зона загрузки: файл кладут, не выбирая папку (шаг ⑤).

Проверяется главное обещание зоны: система узнаёт форму по отпечатку структуры
и раскладывает файл сама, а когда узнать не может — честно оставляет его во
«Входящих» и ждёт человека. Положить файл не в ту папку значит показать
неверные цифры на дашборде без единого признака ошибки, поэтому «угадывать»
здесь нельзя.
"""
from datetime import date

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db  # noqa: E402
from app.modules.documents import storage  # noqa: E402
from app.modules.ingestion import service  # noqa: E402
from app.modules.uploads.service import period_from_filename  # noqa: E402

from pipeline_helpers import (  # noqa: F401,E402 — фикстуры подключаются импортом
    WEEK1, WEEK2, _form, _release, _upload, folder, offline_queue,
)


async def _drop(client, headers, content, filename, monkeypatch, period=None):
    """Файл в общую зону — без папки и (по возможности) без даты."""
    monkeypatch.setattr(storage, "put_object", lambda name, data, ct: f"documents/{name}")
    monkeypatch.setattr(storage, "get_object", lambda path: content)
    data = {"reporting_period_start": period} if period else {}
    r = await client.post(
        "/uploads", headers=headers,
        files={"file": (filename, content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data=data)
    return r


async def test_period_is_read_from_filename():
    """Дата недельной формы есть в её имени — не заставляем вводить руками."""
    assert period_from_filename("Приложение 19.08.2026.xlsx") == date(2026, 8, 19)
    assert period_from_filename("отчет_2026-08-19.xlsx") == date(2026, 8, 19)
    # Ничего похожего на дату — выдумывать нельзя (эндпоинт ответит отказом).
    assert period_from_filename("форма.xlsx") is None
    assert period_from_filename("99.99.2026.xlsx") is None


async def test_known_form_finds_its_folder_by_itself(client, admin_headers, folder, monkeypatch, offline_queue):
    """Главное обещание зоны: знакомая форма уезжает в свою папку сама."""
    # Первый файл размечает и выпускает человек — так у объекта появляется шаблон.
    up1 = await _upload(client, admin_headers, folder["folder_id"], _form(WEEK1), "2026-07-22", monkeypatch)
    await service.run_extraction(up1["extraction_job_id"])
    job = (await client.get(f"/extraction-jobs/{up1['extraction_job_id']}", headers=admin_headers)).json()
    await _release(client, admin_headers, job["job_id"], job["tables"][0], "zupl_code", "2026-07-22")

    # Вторая неделя — уже через общую зону, без выбора папки и без ввода даты.
    r = await _drop(client, admin_headers, _form(WEEK2), "Форма 29.07.2026.xlsx", monkeypatch)
    assert r.status_code == 201, r.text
    up2 = r.json()
    assert up2["period_guessed"] is True and up2["reporting_period_start"] == "2026-07-29"

    async with db.acquire() as conn:
        inbox = await conn.fetchval(
            "select folder_id from documents where id=$1::uuid", up2["id"])
        assert await conn.fetchval("select is_inbox from folders where id=$1", inbox), \
            "до распознавания файл обязан лежать во «Входящих»"

    await service.run_extraction(up2["extraction_job_id"])

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "select folder_id, routed_by, routed_note from documents where id=$1::uuid", up2["id"])
    assert str(row["folder_id"]) == folder["folder_id"], "файл не уехал в папку своей формы"
    assert row["routed_by"] == "template"
    assert "опознана" in row["routed_note"]

    # Журнал импорта отвечает на «куда это попало и почему».
    items = (await client.get("/uploads", headers=admin_headers)).json()["items"]
    mine = next(i for i in items if i["id"] == up2["id"])
    assert mine["in_inbox"] is False and mine["folder_name"] == "ztest_pipe_folder"
    assert mine["object_name"] == "ztest_pipe_obj"
    assert mine["routed_by"] == "template" and mine["state"]


async def test_unknown_form_waits_for_a_human(client, admin_headers, folder, monkeypatch, offline_queue):
    """Незнакомая форма остаётся во «Входящих» — с объяснением и без догадок."""
    r = await _drop(client, admin_headers, _form(WEEK1, extra_col=True),
                    "Незнакомая 05.08.2026.xlsx", monkeypatch)
    up = r.json()
    await service.run_extraction(up["extraction_job_id"])

    async with db.acquire() as conn:
        row = await conn.fetchrow(
            "select d.routed_by, d.routed_note, f.is_inbox from documents d "
            "join folders f on f.id=d.folder_id where d.id=$1::uuid", up["id"])
    assert row["is_inbox"] is True, "чужая папка означала бы неверные цифры на дашборде"
    assert row["routed_by"] is None
    assert "вручную" in row["routed_note"]

    items = (await client.get("/uploads", headers=admin_headers)).json()["items"]
    mine = next(i for i in items if i["id"] == up["id"])
    assert mine["in_inbox"] is True and mine["state"] == "нужна папка"

    # Человек указывает папку сам — и это тоже попадает в журнал.
    r2 = await client.post(f"/uploads/{up['id']}/route", headers=admin_headers,
                           data={"folder_id": folder["folder_id"]})
    assert r2.status_code == 200, r2.text
    items = (await client.get("/uploads", headers=admin_headers)).json()["items"]
    mine = next(i for i in items if i["id"] == up["id"])
    assert mine["in_inbox"] is False and mine["routed_by"] == "manual"

    # Несуществующая папка — отказ, а не молчаливый перенос в никуда.
    bad = await client.post(f"/uploads/{up['id']}/route", headers=admin_headers,
                            data={"folder_id": "00000000-0000-0000-0000-000000000000"})
    assert bad.status_code == 404


async def test_upload_zone_is_closed_for_viewers(client, viewer, monkeypatch):
    """Зрителю зона не доступна: загрузка данных — работа модератора."""
    r = await _drop(client, viewer["headers"], _form(WEEK1), "Форма 12.08.2026.xlsx", monkeypatch)
    assert r.status_code == 403
    assert (await client.get("/uploads", headers=viewer["headers"])).status_code == 403


async def test_upload_without_any_date_is_refused(client, admin_headers, monkeypatch):
    """Отчётную дату выдумать нельзя: по ней строится вся история показателя."""
    r = await _drop(client, admin_headers, _form(WEEK1), "форма.xlsx", monkeypatch)
    assert r.status_code == 400
    assert "дат" in r.json()["detail"].lower()
