"""Авто-выпуск перестаёт быть невидимым (18.08).

Сам авто-выпуск сделан накануне: файл, в точности повторяющий прошлый отчёт,
выпускается без человека. Здесь проверяется ДРУГОЕ — что об этом сказано:

  • в данных есть признак `auto_released`, иначе отличить выпуск автомата от
    выпуска человека нельзя ничем, даже задним числом;
  • создание выпуска попадает в журнал действий (раньше НЕ попадало вовсе —
    ни ручное, ни автоматическое, при том что после выпуска меняются цифры
    на дашбордах);
  • список папки показывает отдельное состояние, а не общее «выпущено»;
  • период, занятый автоматом, объясняется человеку в отказе;
  • папка может отказаться от авто-выпуска, не теряя автоподготовки.
"""
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.ingestion import service

from pipeline_helpers import (  # noqa: F401 — фикстуры подключаются импортом
    WEEK1, WEEK2, _form, _release, _upload, folder, offline_queue,
)


async def _first_week(client, headers, folder, monkeypatch, code="zvis_code"):
    """Первая неделя: её выпускает ЧЕЛОВЕК — шаблона разметки ещё нет."""
    up = await _upload(client, headers, folder["folder_id"], _form(WEEK1), "2026-07-22", monkeypatch)
    await service.run_extraction(up["extraction_job_id"])
    job = (await client.get(f"/extraction-jobs/{up['extraction_job_id']}", headers=headers)).json()
    res = await _release(client, headers, job["job_id"], job["tables"][0], code, "2026-07-22")
    return up, job, res


async def test_auto_release_is_marked_journaled_and_announced(
        client, admin_headers, folder, monkeypatch, offline_queue):
    """Признак в данных, запись в журнале и одно уведомление.

    Ручной выпуск при этом помечен как ручной — иначе признак был бы бесполезен:
    «автоматическими» оказались бы все.
    """
    _, _, manual = await _first_week(client, admin_headers, folder, monkeypatch)

    up2 = await _upload(client, admin_headers, folder["folder_id"], _form(WEEK2), "2026-07-29", monkeypatch)
    await service.run_extraction(up2["extraction_job_id"])

    async with db.acquire() as conn:
        rows = await conn.fetch(
            "select id, reporting_period_start, auto_released from dataset_releases "
            "where object_id=$1::uuid order by reporting_period_start", folder["object_id"])
        assert len(rows) == 2, "вторая неделя должна выпуститься сама"
        assert rows[0]["auto_released"] is False, "первую неделю выпустил человек"
        assert rows[1]["auto_released"] is True, "вторую — автомат"
        auto_id = rows[1]["id"]

        # Журнал действий: обе записи есть, и признак различает их. До этой
        # правки создания выпуска в аудите не было вообще.
        events = await conn.fetch(
            "select entity_id, new_data from audit_log "
            "where entity_type='dataset_release' and action='create' "
            "and entity_id = any($1::uuid[])", [r["id"] for r in rows])
        assert len(events) == 2, "выпуск обязан попадать в журнал независимо от способа"
        import json
        flags = {str(e["entity_id"]): json.loads(e["new_data"])["auto"] for e in events}
        assert flags[manual["release_id"]] is False
        assert flags[str(auto_id)] is True

        # Уведомление — одно, и оно называет файл, период и число значений.
        ev = await conn.fetchrow(
            "select id, event_type, payload from notification_events "
            "where entity_type='dataset_release' and entity_id=$1::uuid", auto_id)
        assert ev is not None and ev["event_type"] == "data.auto_released"
        payload = json.loads(ev["payload"]) if isinstance(ev["payload"], str) else ev["payload"]
        assert payload["document"] == "f_2026-07-29.xlsx"
        assert payload["period"] == "2026-07-29"
        assert payload["values"] and payload["object_id"], payload
        got = await conn.fetchval(
            "select count(*) from notification_recipients where notification_event_id=$1", ev["id"])
        assert got >= 1, "уведомление без получателей никому не показывается"

        # Ручной выпуск никого не уведомляет: человек знает, что нажал кнопку.
        manual_ev = await conn.fetchval(
            "select count(*) from notification_events where entity_type='dataset_release' "
            "and entity_id=$1::uuid", manual["release_id"])
        assert manual_ev == 0


async def test_folder_can_refuse_auto_release_but_keep_preparation(
        client, admin_headers, folder, monkeypatch, offline_queue):
    """Выключенный авто-выпуск оставляет подготовку: файл доходит до «готов».

    Это и есть путь отката для модератора, которому автоматика не нужна:
    мышью, без правки кода.
    """
    await _first_week(client, admin_headers, folder, monkeypatch, code="zvis_off")

    r = await client.patch(
        f"/objects/{folder['object_id']}/folders/{folder['folder_id']}",
        headers=admin_headers, json={"auto_release": False})
    assert r.status_code == 200, r.text
    assert r.json()["auto_release"] is False
    assert r.json()["auto_prepare"] is True, "подготовка не должна выключаться заодно"

    up2 = await _upload(client, admin_headers, folder["folder_id"], _form(WEEK2), "2026-07-29", monkeypatch)
    await service.run_extraction(up2["extraction_job_id"])

    items = (await client.get(f"/folders/{folder['folder_id']}/documents",
                              headers=admin_headers)).json()["items"]
    by_name = {i["original_filename"]: i for i in items}
    # Распознан и размечен шаблоном — но ждёт человека.
    assert by_name["f_2026-07-29.xlsx"]["pipeline"] == "ready", by_name["f_2026-07-29.xlsx"]
    async with db.acquire() as conn:
        n = await conn.fetchval(
            "select count(*) from dataset_releases where object_id=$1::uuid", folder["object_id"])
    assert n == 1, "второй выпуск сделать было некому"


async def test_folder_list_shows_the_flag(client, admin_headers, folder):
    """Тумблер виден в списке папок — иначе им нельзя воспользоваться."""
    r = await client.get(f"/objects/{folder['object_id']}/folders", headers=admin_headers)
    assert r.status_code == 200
    f = next(x for x in r.json() if x["id"] == folder["folder_id"])
    assert f["auto_release"] is True, "по умолчанию включён — так система ведёт себя с 18.08"


async def test_state_and_conflict_explain_the_cause(
        client, admin_headers, folder, monkeypatch, offline_queue):
    """Состояние файла и отказ при ручном выпуске называют ПРИЧИНУ.

    Человек, который сам ничего не выпускал, видит «период занят» и без
    объяснения читает это как поломку.
    """
    await _first_week(client, admin_headers, folder, monkeypatch, code="zvis_conf")

    up2 = await _upload(client, admin_headers, folder["folder_id"], _form(WEEK2), "2026-07-29", monkeypatch)
    await service.run_extraction(up2["extraction_job_id"])

    items = (await client.get(f"/folders/{folder['folder_id']}/documents",
                              headers=admin_headers)).json()["items"]
    auto = next(i for i in items if i["original_filename"] == "f_2026-07-29.xlsx")
    assert auto["pipeline"] == "released_auto"
    hint = auto["pipeline_hint"].lower()
    assert "автоматически" in hint and "отменить выпуск" in hint, auto["pipeline_hint"]

    # Тот же файл человек пробует выпустить сам — период занят автоматом.
    job = (await client.get(f"/extraction-jobs/{up2['extraction_job_id']}", headers=admin_headers)).json()
    table = job["tables"][0]
    body = {
        "table_id": table["id"], "code": "zvis_conf", "name": "Форма 2026-07-29",
        "reporting_period_start": "2026-07-29", "supersede": False,
        "fields": [{
            "column_index": c["column_index"],
            "field_code": ["subject", "obr", "uved"][c["column_index"] - 1],
            "field_name": ["Субъект", "Обращения", "Уведомления"][c["column_index"] - 1],
            "data_type": "text" if c["column_index"] == 1 else "number",
            "is_row_label": c["column_index"] == 1,
        } for c in table["columns"] if c["column_index"] > 0],
        "layout": {"data_rect": table["data_rect"] or [0, 0, 2, 3], "header_rows": 2,
                   "orientation": "columns", "skip_rows": []},
    }
    r = await client.post(f"/extraction-jobs/{job['job_id']}/release", headers=admin_headers, json=body)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["existing"]["auto"] is True, "иначе окно не сможет объяснить причину"
    assert "автоматически" in detail["message"].lower()
    assert "заместить" in detail["message"].lower(), "отказ обязан показывать выход"
