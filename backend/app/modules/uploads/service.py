"""Логика общей зоны загрузки.

Раньше, чтобы сдать недельную форму, человек обязан был знать устройство
системы: выбрать объект, потом папку внутри него, потом дату. Отпечаток
структуры формы у нас есть с 15.08 (`object_layout_templates.fingerprint`) —
и его достаточно, чтобы узнать бланк «в лицо» сразу после распознавания.

Порядок такой: файл кладётся в служебную папку «Входящие», распознаётся, и
воркер сверяет его отпечаток со ВСЕМИ формами организации. Совпала ровно одна —
документ уезжает в ту папку, откуда приходили прошлые такие файлы, и дальше всё
идёт по обычному пути (сверка с шаблоном, авто-выпуск). Совпало несколько или
ни одной — файл остаётся во «Входящих» и ЖДЁТ человека: чужая папка означала бы
неверные цифры на дашборде без единого признака ошибки.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional

log = logging.getLogger(__name__)

INBOX_NAME = "Входящие"
JOURNAL_LIMIT = 50

# Дата в имени файла: у заказчика недельные формы называются
# «Приложение_к_Протоколу_новая_форма 19.08.2026.xlsx».
_DATE_PATTERNS = [
    (re.compile(r"(\d{2})[.\-_](\d{2})[.\-_](\d{4})"), ("d", "m", "y")),
    (re.compile(r"(\d{4})[.\-_](\d{2})[.\-_](\d{2})"), ("y", "m", "d")),
]


def period_from_filename(filename: str) -> Optional[date]:
    """Отчётная дата, вычитанная из имени файла.

    Только предложение, а не решение: человек видит её в поле и правит. Пустое
    поле в зоне загрузки — главное трение, ради снятия которого зона и делается,
    но выдумывать дату вместо человека нельзя.
    """
    for rx, order in _DATE_PATTERNS:
        m = rx.search(filename or "")
        if not m:
            continue
        parts = dict(zip(order, m.groups(), strict=False))
        try:
            return date(int(parts["y"]), int(parts["m"]), int(parts["d"]))
        except ValueError:
            continue
    return None


async def inbox_folder(conn, org_id, user_id) -> str:
    """Служебная папка «Входящие» организации (создаётся при первом обращении).

    Признак хранится колонкой `folders.is_inbox`, а не именем: имя человек
    вправе поменять, а система обязана продолжать узнавать свою папку.
    """
    fid = await conn.fetchval(
        "select id from folders where organization_id=$1 and is_inbox limit 1", org_id)
    if fid:
        return str(fid)
    fid = await conn.fetchval(
        "insert into folders(organization_id, name, description, created_by, is_inbox, "
        "  auto_prepare, auto_release) "
        "values($1,$2,$3,$4,true,true,false) returning id",
        org_id, INBOX_NAME,
        "Служебная папка общей зоны загрузки: файлы лежат здесь, пока система не "
        "опознает форму и не разложит их по папкам.", user_id)
    return str(fid)


async def _target_folder(conn, match: dict) -> Optional[str]:
    """Куда класть файл опознанной формы — туда, откуда приходили прошлые.

    Папка берётся у документа, из которого выпущены данные шаблона: именно в неё
    складывают эту форму. Запасной путь — папка объекта с автоподготовкой:
    объект может быть заведён заново, а данные перенесены.
    """
    if match.get("source_release_id"):
        fid = await conn.fetchval(
            "select d.folder_id from dataset_releases r "
            "join document_versions v on v.id = r.source_document_version_id "
            "join documents d on d.id = v.document_id "
            "where r.id=$1 and d.folder_id is not null", match["source_release_id"])
        if fid:
            return str(fid)
    fid = await conn.fetchval(
        "select id from folders where object_id=$1 and not is_inbox "
        "order by auto_prepare desc, created_at limit 1", match["object_id"])
    return str(fid) if fid else None


async def route_after_extraction(conn, job_id: str) -> None:
    """Разложить распознанный файл из «Входящих» по отпечатку его формы.

    Вызывается воркером ДО сверки с шаблоном и авто-выпуска: те работают уже с
    объектом папки, поэтому маршрут должен быть определён раньше. Сбой не должен
    ронять распознавание — файл разобран, и потерять результат из-за подсказки
    было бы обиднее всего.
    """
    from ..ingestion import mapping
    try:
        doc = await conn.fetchrow(
            "select d.id, d.organization_id, d.folder_id, d.original_filename "
            "from extraction_jobs ej "
            "join document_versions v on v.id = ej.document_version_id "
            "join documents d on d.id = v.document_id "
            "join folders f on f.id = d.folder_id "
            "where ej.id=$1::uuid and f.is_inbox", job_id)
        if doc is None:
            return  # файл загружали в конкретную папку — маршрутизировать нечего
        tables = await conn.fetch(
            "select id from extracted_tables where extraction_job_id=$1::uuid order by table_index", job_id)
        matches = await mapping.match_any_template(
            conn, doc["organization_id"], [str(t["id"]) for t in tables])
        if not matches:
            await _note(conn, doc["id"], None,
                        "Форма незнакомая: такой структуры в системе ещё нет. "
                        "Укажите папку вручную — после первого выпуска система запомнит бланк "
                        "и следующий такой файл разложит сама.")
            return
        if len(matches) > 1:
            names = ", ".join(f"«{m['object_name']}»" for m in matches[:3])
            await _note(conn, doc["id"], None,
                        f"Структура совпала с несколькими формами ({names}) — выберите папку сами: "
                        "положить файл не туда значит показать неверные цифры на дашборде.")
            return
        m = matches[0]
        folder_id = await _target_folder(conn, m)
        if not folder_id:
            await _note(conn, doc["id"], None,
                        f"Форма опознана («{m['object_name']}»), но у объекта нет подходящей папки — "
                        "укажите её вручную.")
            return
        await conn.execute(
            "update documents set folder_id=$2::uuid, routed_by='template', routed_note=$3, "
            "routed_at=now() where id=$1",
            doc["id"], folder_id,
            f"Форма опознана по структуре: «{m['object_name']}»"
            + (f" · набор данных {m['dataset_code']}" if m.get("dataset_code") else ""))
    except Exception as exc:  # noqa: BLE001 — маршрут не важнее самого разбора
        log.warning("Маршрутизация файла по заданию %s не удалась: %s", job_id, exc)


async def _note(conn, document_id, routed_by: Optional[str], note: str) -> None:
    await conn.execute(
        "update documents set routed_by=$2, routed_note=$3, routed_at=now() where id=$1",
        document_id, routed_by, note)


async def journal(conn, org_id, limit: int = JOURNAL_LIMIT, period: Optional[date] = None) -> list:
    """Журнал импорта: что загрузили, куда это уехало и на чём стоит сейчас.

    Собирается запросом по документам, а не отдельной таблицей событий: иначе
    журнал и реальное состояние файлов однажды разошлись бы.

    `period` — необязательный фильтр по ОТЧЁТНОЙ дате (не по дате загрузки):
    находит именно тот отчёт, а не всё, что грузили в этот день. Фильтрация в
    самом запросе, а не на клиенте по уже показанным строкам — иначе старый
    отчёт, вытесненный из последних `limit`, нашёлся бы не всегда.
    """
    rows = await conn.fetch(
        "select d.id, d.original_filename, d.reporting_period_start, d.created_at, "
        "  d.routed_by, d.routed_note, d.status::text as status, "
        "  f.name as folder_name, f.is_inbox, o.name as object_name, "
        "  u.full_name, u.login, "
        "  (select ej.status::text from extraction_jobs ej join document_versions v2 on v2.id=ej.document_version_id "
        "   where v2.document_id=d.id order by ej.created_at desc limit 1) as job_status, "
        "  (select ej.template_match from extraction_jobs ej join document_versions v2 on v2.id=ej.document_version_id "
        "   where v2.document_id=d.id order by ej.created_at desc limit 1) as template_match, "
        "  exists(select 1 from dataset_releases r join document_versions v3 on v3.id=r.source_document_version_id "
        "         where v3.document_id=d.id and r.status<>'superseded') as released "
        "from documents d "
        "left join folders f on f.id=d.folder_id "
        "left join objects o on o.id=f.object_id "
        "left join users u on u.id=d.uploaded_by "
        "where d.organization_id=$1 and ($3::date is null or d.reporting_period_start = $3) "
        "order by d.created_at desc limit $2", org_id, limit, period)
    out = []
    for r in rows:
        out.append({
            "id": str(r["id"]),
            "filename": r["original_filename"],
            "period": r["reporting_period_start"].isoformat() if r["reporting_period_start"] else None,
            "uploaded_at": r["created_at"].isoformat() if r["created_at"] else None,
            "uploaded_by": r["full_name"] or r["login"],
            "folder_name": r["folder_name"],
            "object_name": r["object_name"],
            "in_inbox": bool(r["is_inbox"]),
            "routed_by": r["routed_by"],
            "routed_note": r["routed_note"],
            "state": _state(r),
            "released": r["released"],
        })
    return out


def _state(r) -> str:
    """Одно человеческое состояние вместо трёх машинных статусов.

    Те же формулировки, что в списке папки (15.08): человек не должен гадать,
    значит ли «extracted» готовность.
    """
    if r["released"]:
        return "данные выпущены"
    if r["is_inbox"]:
        if r["job_status"] in (None, "queued", "running"):
            return "распознаётся…"
        if r["job_status"] == "failed":
            return "⚠ не распознан"
        return "нужна папка"
    if r["job_status"] == "failed":
        return "⚠ не распознан"
    if r["job_status"] in (None, "queued", "running"):
        return "распознаётся…"
    if r["template_match"] == "exact":
        return "✓ данные подготовлены"
    if r["template_match"] in ("structure_differs", "none"):
        return "⚠ требует внимания"
    return "нужна разметка"


async def known_forms(conn, org_id) -> list:
    """Список форм, которые «📥 Загрузка» уже узнаёт сама — подсказка человеку,
    что можно просто перетащить, а что уйдёт на ручную разметку.

    Источник — тот же `object_layout_templates`, что использует
    `route_after_extraction` для сопоставления по отпечатку: подсказка не
    может разойтись с реальным поведением загрузки, потому что читает ровно
    то же самое место. Один шаблон = одна распознаваемая форма (объект).
    """
    # Папка считается ТЕМ ЖЕ правилом, что реальная маршрутизация
    # (`_target_folder`): сперва папка документа-источника шаблона, а если он
    # уже удалён (например, был тестовым и его почистили) — любая обычная
    # папка объекта. Иначе подсказка сказала бы «некуда» там, где загрузка на
    # самом деле сработает.
    rows = await conn.fetch(
        "select t.object_id, o.name as object_name, t.dataset_code, t.updated_at, "
        "  t.row_count, doc.original_filename as example_filename, "
        "  coalesce(fr.name, ff.name) as folder_name, "
        "  (select count(*) from dataset_releases r2 "
        "   where r2.code = t.dataset_code and r2.status <> 'superseded') as periods_loaded "
        "from object_layout_templates t "
        "join objects o on o.id = t.object_id "
        "left join dataset_releases rel on rel.id = t.source_release_id "
        "left join document_versions v on v.id = rel.source_document_version_id "
        "left join documents doc on doc.id = v.document_id "
        "left join folders fr on fr.id = doc.folder_id "
        "left join lateral ("
        "  select f.name from folders f where f.object_id = t.object_id and not f.is_inbox "
        "  order by f.auto_prepare desc, f.created_at limit 1"
        ") ff on fr.id is null "
        "where o.organization_id = $1 "
        "order by o.name", org_id)
    return [{
        "object_id": str(r["object_id"]),
        "object_name": r["object_name"],
        "dataset_code": r["dataset_code"],
        "folder_name": r["folder_name"],
        "example_filename": r["example_filename"],
        "row_count": r["row_count"],
        "periods_loaded": r["periods_loaded"],
        "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
    } for r in rows]


async def route_manually(conn, org_id, document_id: str, folder_id: str, user_id) -> dict:
    """Человек указал папку сам — файл уезжает туда, а решение попадает в журнал."""
    doc = await conn.fetchrow(
        "select d.id, d.original_filename from documents d where d.id=$1::uuid and d.organization_id=$2",
        document_id, org_id)
    if doc is None:
        raise LookupError("Документ не найден")
    ok = await conn.fetchval(
        "select 1 from folders where id=$1::uuid and organization_id=$2 and not is_inbox",
        folder_id, org_id)
    if not ok:
        raise LookupError("Папка не найдена")
    await conn.execute(
        "update documents set folder_id=$2::uuid, routed_by='manual', routed_note=$3, "
        "routed_at=now() where id=$1::uuid", document_id, folder_id, "Папку указал человек")
    return {"id": str(doc["id"]), "folder_id": folder_id}
