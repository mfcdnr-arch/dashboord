"""Книга приходит повторно: побеждает более свежий файл, но переливается только
изменившееся.

До 22.09.2026 правило было «дата уже загружена — пропускаем». Оно защищало от
перезаливки всей истории при дописанном листе, но молча теряло ИСПРАВЛЕНИЯ:
заказчик прислал книгу за год, в которой июль и август отличались от того, что
уже лежало в системе, — и система оставила прежние цифры, не сказав об этом ни
слова.

Здесь проверяется новое правило целиком: тот же файл не трогаем, более старый
файл не пускаем поверх свежего, а у равного по праву — сверяем СОДЕРЖИМОЕ и
перевыпускаем только то, что изменилось.
"""
import io
from datetime import date

import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.ingestion import mapping, service

from pipeline_helpers import (  # noqa: F401 — фикстуры подключаются импортом
    _upload, folder, offline_queue,
)

CODE = "ztest_book_code"


def _book(sheets: dict) -> bytes:
    """Книга, где ЛИСТ = отчётная дата: {«01.07»: [(строка, обращения, увед.)]}."""
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title=title)
        ws.append(["Субъект", "Обращения", "Уведомления"])
        ws.append(["1", "2", "3"])
        for r in rows:
            ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _load(client, headers, folder_id, content, period, monkeypatch):
    up = await _upload(client, headers, folder_id, content, period, monkeypatch)
    await service.run_extraction(up["extraction_job_id"])
    return up["extraction_job_id"]


async def _by_sheet(client, headers, job_id, **extra):
    body = {"code": CODE, "name": "Книга по листам", "year": 2026,
            "layout": {"data_rect": None, "header_rows": 2,
                       "orientation": "columns", "skip_rows": []}}
    body.update(extra)
    r = await client.post(f"/extraction-jobs/{job_id}/release-by-sheet",
                          headers=headers, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def _active(code=CODE):
    """Активные выпуски: период → (id, число обращений в первой строке)."""
    async with db.acquire() as conn:
        rows = await conn.fetch(
            "select r.id, r.reporting_period_start as p, "
            "  (select v.value_number from dataset_values v "
            "   where v.dataset_release_id=r.id and v.canonical_field_code like 'obr%' "
            "   order by v.row_index limit 1) as obr "
            "from dataset_releases r where r.code=$1 and r.status<>'superseded' "
            "order by r.reporting_period_start", code)
        return {r["p"].isoformat(): (str(r["id"]), float(r["obr"]) if r["obr"] is not None else None)
                for r in rows}


WEEK = {"01.07": [("ДНР", 100, 10)], "08.07": [("ДНР", 200, 20)], "15.07": [("ДНР", 300, 30)]}


async def test_same_file_run_again_touches_nothing(
        client, admin_headers, folder, monkeypatch, offline_queue):
    """Повторный прогон ТОГО ЖЕ файла не разбирает листы и не трогает данные.

    Это дозаливка прерванного прогона — на настоящей книге она случилась дважды
    подряд, и стоить она должна нисколько.
    """
    job = await _load(client, admin_headers, folder["folder_id"], _book(WEEK), "2026-07-15", monkeypatch)
    first = await _by_sheet(client, admin_headers, job)
    assert first["released"] == 3, first
    assert first["replaced"] == 0, "первая загрузка ничего не замещает"
    before = await _active()

    again = await _by_sheet(client, admin_headers, job)
    assert again["released"] == 0
    assert len(again["skipped"]) == 3
    assert all("этого же файла" in s["reason"] for s in again["skipped"]), again["skipped"]
    assert await _active() == before, "повторный прогон не имеет права менять выпуски"


async def test_newer_book_replaces_only_changed_sheets(
        client, admin_headers, folder, monkeypatch, offline_queue):
    """Свежая книга: исправленный день перевыпущен, неизменившиеся оставлены.

    Главное здесь — ИЗБИРАТЕЛЬНОСТЬ. Перелить всю книгу было бы правильно по
    данным и разорительно по объёму (замещённые выпуски остаются — их
    возвращают кнопкой), а пропустить всё — потерять исправление.
    """
    old = await _load(client, admin_headers, folder["folder_id"], _book(WEEK), "2026-07-15", monkeypatch)
    await _by_sheet(client, admin_headers, old)

    fixed = dict(WEEK)
    fixed["08.07"] = [("ДНР", 222, 20)]          # ведомство переписало цифру
    fixed["22.07"] = [("ДНР", 400, 40)]          # и дописало новый лист
    new = await _load(client, admin_headers, folder["folder_id"], _book(fixed), "2026-07-22", monkeypatch)
    res = await _by_sheet(client, admin_headers, new)

    kept = [s for s in res["skipped"] if "не изменился" in s["reason"]]
    assert len(kept) == 2, res["skipped"]
    assert res["released"] == 2 and res["replaced"] == 1, res
    replaced = [c for c in res["created"] if c.get("replaced")]
    assert [c["period"] for c in replaced] == ["2026-07-08"], res["created"]

    act = await _active()
    assert act["2026-07-08"][1] == 222, "на дашборде обязана быть исправленная цифра"
    assert act["2026-07-01"][1] == 100 and act["2026-07-15"][1] == 300
    assert "2026-07-22" in act, "дописанный лист должен выпуститься"

    async with db.acquire() as conn:
        # Прежний выпуск не уничтожен, а снят с использования: решение обратимо.
        old_n = await conn.fetchval(
            "select count(*) from dataset_releases where code=$1 and status='superseded' "
            "and reporting_period_start=$2", CODE, date(2026, 7, 8))
    assert old_n == 1


async def test_older_book_does_not_overwrite_newer(
        client, admin_headers, folder, monkeypatch, offline_queue):
    """Старый файл, загруженный позже, не затирает данные свежего.

    Порядок загрузки и свежесть данных — разные вещи: модератор мог поднять
    прошлогоднюю книгу, чтобы посмотреть, и её прогон не должен откатывать
    цифры на полгода назад.
    """
    old = await _load(client, admin_headers, folder["folder_id"], _book(WEEK), "2026-07-15", monkeypatch)
    fixed = dict(WEEK)
    fixed["08.07"] = [("ДНР", 222, 20)]
    new = await _load(client, admin_headers, folder["folder_id"], _book(fixed), "2026-07-22", monkeypatch)
    await _by_sheet(client, admin_headers, new)          # свежая книга выпущена

    res = await _by_sheet(client, admin_headers, old)     # и только теперь — старая
    assert res["released"] == 0, res
    assert all("старше" in s["reason"] for s in res["skipped"]), res["skipped"]
    assert (await _active())["2026-07-08"][1] == 222, "цифра свежей книги обязана уцелеть"


async def test_explicit_supersede_still_forces_everything(
        client, admin_headers, folder, monkeypatch, offline_queue):
    """Явное «заместить» остаётся рычагом человека и перевыпускает всё подряд.

    Сверка содержимого — умолчание, а не запрет: модератор должен иметь
    возможность перелить книгу целиком, не доказывая системе, что данные
    изменились.
    """
    job = await _load(client, admin_headers, folder["folder_id"], _book(WEEK), "2026-07-15", monkeypatch)
    await _by_sheet(client, admin_headers, job)
    res = await _by_sheet(client, admin_headers, job, supersede=True)
    assert res["released"] == 3 and res["replaced"] == 3, res


def test_skip_reason_names_the_three_cases():
    """Чистое правило «кто главнее» — три ветки, и каждая называется словами."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    same = {"source_document_version_id": "v1", "uploaded_at": now - timedelta(days=1)}
    assert "этого же файла" in mapping._resupply_skip_reason(same, "v1", now)

    fresher = {"source_document_version_id": "v2", "uploaded_at": now}
    assert "старше" in mapping._resupply_skip_reason(fresher, "v1", now - timedelta(days=1))

    older = {"source_document_version_id": "v2", "uploaded_at": now - timedelta(days=5)}
    assert mapping._resupply_skip_reason(older, "v1", now) is None, "свежий файл имеет право на сверку"

    # Источника у прежнего выпуска нет вовсе — спорить не с чем, решает отпечаток.
    orphan = {"source_document_version_id": None, "uploaded_at": None}
    assert mapping._resupply_skip_reason(orphan, "v1", now) is None


def test_digest_compares_numbers_and_not_their_spelling():
    """Отпечаток сравнивает ЧИСЛА, а не записи, и не зависит от порядка выборки.

    Свежее значение приходит из разбора типом float, а прочитанное из БД —
    Decimal. Сравнивай мы записи, «1.0» и «1.00» разошлись бы, и система
    объявляла бы неизменившийся лист изменившимся — то есть переливала бы всю
    историю при каждой загрузке.
    """
    from decimal import Decimal

    a = [(0, "ДНР", "obr", None, 100.0, None), (0, "ДНР", "uved", None, 10.0, None)]
    b = [(0, "ДНР", "uved", None, Decimal("10.00"), None),
         (0, "ДНР", "obr", None, Decimal("100"), None)]
    assert mapping.values_digest(a) == mapping.values_digest(b)

    changed = [(0, "ДНР", "obr", None, 101.0, None), (0, "ДНР", "uved", None, 10.0, None)]
    assert mapping.values_digest(a) != mapping.values_digest(changed)

    # Лишний столбец в книге обязан считаться изменением, даже если числа те же.
    renamed = [(0, "ДНР", "obr_2", None, 100.0, None), (0, "ДНР", "uved", None, 10.0, None)]
    assert mapping.values_digest(a) != mapping.values_digest(renamed)

    # Пустая ячейка и ноль — разные вещи.
    empty = [(0, "ДНР", "obr", None, None, None), (0, "ДНР", "uved", None, 10.0, None)]
    zero = [(0, "ДНР", "obr", None, 0.0, None), (0, "ДНР", "uved", None, 10.0, None)]
    assert mapping.values_digest(empty) != mapping.values_digest(zero)
