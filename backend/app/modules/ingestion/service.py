"""Оркестрация задания извлечения: файл (MinIO) → парсер → запись в БД.

Выполняется в фоновом воркере (arq). Заполняет:
  extraction_jobs (статус/тайминги/уверенность/предупреждения),
  extracted_tables (шапка, счётчики, предпросмотр, полная сетка),
  extracted_columns (составной заголовок, тип, уверенность, канон. поле — позже).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import List

from ... import db
from ..documents import storage
from . import analyze, parsers

log = logging.getLogger(__name__)

PREVIEW_ROWS = 100  # усечение предпросмотра для UI (открытый вопрос док-06 — дефолт)


async def run_extraction(job_id: str) -> None:
    """Полный прогон одного задания извлечения (по id из extraction_jobs)."""
    pool = db.get_pool()
    async with pool.acquire() as conn:
        job = await conn.fetchrow(
            "select ej.id, ej.document_version_id, dv.storage_path, d.source_type, d.id as document_id "
            "from extraction_jobs ej "
            "join document_versions dv on dv.id = ej.document_version_id "
            "join documents d on d.id = dv.document_id "
            "where ej.id = $1::uuid",
            job_id,
        )
        if job is None:
            return
        await conn.execute(
            "update extraction_jobs set status='running', started_at=now(), error_message=null "
            "where id=$1::uuid",
            job_id,
        )
        await conn.execute(
            "update documents set status='parsing' where id=$1", job["document_id"]
        )

    try:
        content = await asyncio.to_thread(storage.get_object, job["storage_path"])
        result = await asyncio.to_thread(parsers.parse, content, job["source_type"])
    except Exception as exc:  # noqa: BLE001 — любая ошибка парсинга должна пометить job
        await _fail(job_id, job["document_id"], str(exc))
        return

    confidences: List[float] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            # очистка прежних результатов (повторный прогон)
            await conn.execute(
                "delete from extracted_tables where extraction_job_id=$1::uuid", job_id
            )
            for tbl in result.tables:
                # Анализ идёт по сетке с развёрнутыми объединениями, а хранится и
                # рисуется — исходная: объединение должно попасть в предпросмотр
                # как rowspan/colspan, а не размножиться по столбцам.
                filled = parsers.fill_merges(tbl.rows, tbl.merges)
                rect = analyze.detect_data_rect(tbl.rows, tbl.merges)
                header_rows = analyze.guess_header_rows(filled, rect)
                columns = analyze.analyze_columns(filled, header_rows, rect)
                confidences.extend(c.confidence for c in columns)
                preview = tbl.rows[:PREVIEW_ROWS]
                et = await conn.fetchrow(
                    "insert into extracted_tables(extraction_job_id, sheet_or_page, table_index, "
                    "row_count, column_count, header_rows, raw_preview, data, merges, data_rect) "
                    "values($1::uuid,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb,$9::jsonb,$10::jsonb) returning id",
                    job_id, tbl.sheet_or_page, tbl.table_index,
                    tbl.row_count, tbl.column_count, header_rows,
                    json.dumps(preview, ensure_ascii=False),
                    json.dumps(tbl.rows, ensure_ascii=False),
                    json.dumps([list(m) for m in tbl.merges], ensure_ascii=False),
                    json.dumps(list(rect), ensure_ascii=False),
                )
                for col in columns:
                    await conn.execute(
                        "insert into extracted_columns(extracted_table_id, column_index, "
                        "source_header, inferred_type, confidence_score) "
                        "values($1,$2,$3,$4,$5)",
                        et["id"], col.column_index, col.source_header,
                        col.inferred_type, col.confidence,
                    )

    avg_conf = round(sum(confidences) / len(confidences), 4) if confidences else None
    # нет таблиц или есть предупреждения → нужна ручная проверка (needs_review)
    status = "succeeded" if result.tables and not result.warnings else "needs_review"
    async with pool.acquire() as conn:
        await conn.execute(
            "update extraction_jobs set status=$2::extraction_job_status, finished_at=now(), "
            "confidence_score=$3, warnings=$4::jsonb where id=$1::uuid",
            job_id, status, avg_conf,
            json.dumps(result.warnings, ensure_ascii=False),
        )
        await _check_template(conn, job_id)
        # Совпал бланк и нет замечаний — выпускаем сразу: заказчик просил, чтобы
        # план/факт пересчитывался при добавлении файла, а не после ручного шага.
        await _auto_release(conn, job_id)
        await conn.execute(
            "update documents set status='extracted' where id=$1", job["document_id"]
        )


async def _check_template(conn, job_id: str) -> None:
    """Сверка с шаблоном объекта сразу после распознавания.

    Вердикт пишется в задание, чтобы список документов в папке показывал
    состояние каждого файла («данные подготовлены» / «требует внимания») без
    пересчёта разметки на каждый файл: разбор сетки стоит дорого, а в папке их
    десятки. Сам конструктор считает сверку заново — он должен работать и на
    заданиях, распознанных до появления этой проверки.

    Сбой сверки не должен ронять распознавание: файл уже разобран, и потерять
    результат из-за подсказки было бы обиднее всего.
    """
    from . import mapping  # локальный импорт: mapping тянет analyze/parsers
    try:
        ctx = await mapping.resolve_context(conn, job_id)
        if ctx is None or ctx["object_id"] is None:
            return
        tables = await conn.fetch(
            "select id from extracted_tables where extraction_job_id=$1::uuid order by table_index", job_id)
        tpl = await mapping.layout_template_for_tables(
            conn, ctx["object_id"], [str(t["id"]) for t in tables])
        if tpl is None:
            match, note = "none", "Разметка этой формы ещё не сохранена — разметьте файл, и следующий придёт готовым."
        else:
            match, note = tpl["match"], tpl["note"]
        await conn.execute(
            "update extraction_jobs set template_match=$2, template_note=$3 where id=$1::uuid",
            job_id, match, note)
    except Exception as exc:  # noqa: BLE001 — подсказка не важнее самого разбора
        log.warning("Сверка с шаблоном не удалась для задания %s: %s", job_id, exc)


async def _auto_release(conn, job_id: str) -> None:
    """Выпуск данных без участия человека — когда файл в точности повторяет
    прошлый (запрос заказчика 17.08).

    Раньше правило было «автомат готовит — выпускает человек» (15.08), и оно
    остаётся для всего, что хоть чем-то отличается. Автоматически выпускаем
    только при СОВПАДЕНИИ ВСЕХ условий сразу:

      • у папки включена автоподготовка (тот же тумблер, что запускает
        распознавание: папка «на хранение» не должна попадать в дашборды);
      • и отдельно — не снят тумблер авто-выпуска: «готовь без меня» и
        «выпускай без меня» это разные решения, и второе папка может
        отменить, не теряя первого;
      • отпечаток структуры совпал с прошлым выпуском (`match == exact`) —
        изменившийся бланк по-прежнему ждёт человека, потому что чужая
        разметка дала бы неверные цифры молча;
      • число строк тоже совпало (`rows_differ` ложно): появился новый субъект
        — позиционно снятые строки переносить нельзя, исключение «строка 4»
        выбросило бы данные того, кто встал на её место;
      • у файла указана отчётная дата и за неё ЕЩЁ НЕТ выпуска — замещать
        существующие данные автоматически нельзя, это потеря информации;
      • проверки качества не дали ни одного замечания. Именно они ловят
        главную беду недельных форм: перенесённые без изменения строки,
        уменьшившийся накопительный итог, недельное больше накопительного.

    Любая осечка не должна ронять распознавание: файл уже разобран, и терять
    результат из-за неудавшегося выпуска нельзя — человек всё равно сможет
    выпустить его кнопкой.
    """
    from . import mapping
    try:
        job = await conn.fetchrow(
            "select ej.id, ej.template_match, ej.document_version_id, "
            "       d.reporting_period_start, d.original_filename, f.auto_prepare, "
            "       f.auto_release, f.name as folder_name, d.organization_id "
            "from extraction_jobs ej "
            "join document_versions dv on dv.id = ej.document_version_id "
            "join documents d on d.id = dv.document_id "
            "join folders f on f.id = d.folder_id "
            "where ej.id = $1::uuid", job_id)
        if job is None or not job["auto_prepare"] or job["template_match"] != "exact":
            return
        if job["auto_release"] is False:
            # Автоподготовка и авто-выпуск — РАЗНЫЕ решения: «готовь без меня»
            # не означает «выпускай без меня». Папка вправе отказаться от
            # второго, оставив первое.
            return
        if job["reporting_period_start"] is None:
            return

        ctx = await mapping.resolve_context(conn, job_id)
        if ctx is None or ctx["object_id"] is None:
            return
        tables = await conn.fetch(
            "select id from extracted_tables where extraction_job_id=$1::uuid order by table_index", job_id)
        tpl = await mapping.layout_template_for_tables(
            conn, ctx["object_id"], [str(t["id"]) for t in tables])
        if tpl is None or tpl.get("match") != "exact" or not tpl.get("table_id"):
            return
        if tpl.get("rows_differ"):
            # Состав граф тот же, но СТРОК стало другое число: в форме появился
            # (или исчез) субъект. Позиционно снятые строки при этом переносить
            # нельзя — исключение «строка 4» выбросило бы данные того, кто встал
            # на её место. Такой файл смотрит человек.
            return
        code = tpl.get("dataset_code")
        fields = tpl.get("fields") or []
        if not code or not fields:
            return

        period = job["reporting_period_start"]
        exists = await conn.fetchval(
            "select 1 from dataset_releases where organization_id=$1 and code=$2 "
            "and reporting_period_start=$3 and status <> 'superseded'",
            job["organization_id"], code, period)
        if exists:
            # За этот период данные уже есть. Замещать их автоматически нельзя:
            # решение «эти цифры теперь неверны» принимает человек.
            return

        warnings = await _auto_quality(conn, job, tpl, code, period, fields)
        if warnings:
            # Замечания есть — оставляем файл человеку. Он увидит их в панели
            # выпуска и решит сам; молча выпустить сомнительные данные хуже,
            # чем подождать.
            return

        # Автор выпуска — тот, кто загрузил файл: в журнале должно быть видно
        # живого человека, а не «система». Колонка называется uploaded_by.
        author = await conn.fetchval(
            "select uploaded_by from document_versions where id=$1", job["document_version_id"])
        res = await mapping.build_release(
            conn, job_id=str(job_id), table_id=str(tpl["table_id"]), code=code,
            name=job["original_filename"] or code,
            reporting_period_start=period, reporting_period_end=None,
            fields=fields, layout=tpl.get("layout"), cells=tpl.get("cells") or [],
            supersede=False, user={"id": author}, auto=True,
        )
        await _announce_auto_release(conn, job, code, period, res, author, ctx["object_id"])
        log.info("Авто-выпуск: задание %s, набор %s, отчёт за %s", job_id, code, period)
    except Exception as exc:  # noqa: BLE001 — выпуск не важнее самого разбора
        log.warning("Авто-выпуск не выполнен для задания %s: %s", job_id, exc)


async def _announce_auto_release(conn, job, code: str, period, res: dict, author, object_id) -> None:
    """След авто-выпуска: запись в журнал действий и одно уведомление.

    **Создание выпуска до сих пор не попадало в аудит вообще** — ни ручное, ни
    автоматическое (там были только отмена, возврат и удаление). Это самая
    ответственная операция конвейера: после неё меняются цифры на дашбордах,
    и на вопрос «откуда взялись эти данные» журнал не отвечал. Пишем оба
    случая, признак `auto` различает их.

    Уведомление — ОДНО на выпуск и только при автоматическом: человек, нажавший
    кнопку сам, в сообщении о своём же действии не нуждается. Получатели —
    загрузивший файл (он узнает, что делать больше ничего не нужно) и
    управляющие: данные ушли на дашборды без их участия, и они вправе это
    увидеть в тот же день, а не через неделю.
    """
    from ..audit import service as audit_svc
    from ..notifications import service as notif_svc

    # `object_id` — чтобы клик по уведомлению вёл к объекту, где лежит файл:
    # у выпуска своего экрана нет, а уведомление без перехода — тупик.
    payload = {
        "code": code, "period": str(period), "auto": True,
        "values": res.get("values_count"), "rows": res.get("rows"),
        "document": job["original_filename"], "folder": job["folder_name"],
        "object_id": str(object_id) if object_id else None,
    }
    await audit_svc.write_event(
        conn, job["organization_id"], author, "create", "dataset_release",
        res["release_id"], new_data=payload)

    recipients = set(await notif_svc.management_user_ids(conn, job["organization_id"]))
    if author:
        recipients.add(author)
    await notif_svc.notify(
        conn, job["organization_id"], "data.auto_released", "dataset_release",
        res["release_id"], payload, list(recipients))


async def _auto_quality(conn, job, tpl: dict, code: str, period, fields: list) -> list:
    """Те же проверки качества, что видит человек перед кнопкой «Выпустить».

    Считаются ТЕМ ЖЕ кодом (`mapping.quality_warnings`), иначе «автомат выпустил
    молча, а у человека были бы замечания» стало бы неизбежным.
    """
    from . import mapping
    row = await conn.fetchrow(
        "select data, merges, header_rows from extracted_tables where id=$1::uuid", tpl["table_id"])
    if row is None:
        return []
    import json as _json
    grid = _json.loads(row["data"]) if isinstance(row["data"], str) else (row["data"] or [])
    raw_merges = _json.loads(row["merges"]) if isinstance(row["merges"], str) else (row["merges"] or [])
    merges = [tuple(m) for m in raw_merges]
    lay = {**mapping.DEFAULT_LAYOUT, **(tpl.get("layout") or {})}
    hdr = int((row["header_rows"] if lay.get("header_rows") is None else lay["header_rows"]) or 0)
    # Ориентация может лежать в шаблоне явным null (разметка, сохранённая до
    # появления поля) — берём умолчание, иначе сетка считалась бы «как выйдет».
    area = mapping.analysis_grid(
        grid, merges, lay.get("data_rect"),
        lay.get("orientation") or mapping.DEFAULT_LAYOUT["orientation"])
    rows = mapping.data_rows(area, hdr, lay.get("skip_rows") or [])
    label = next((f["column_index"] for f in fields if f.get("is_row_label")), None)
    return await mapping.quality_warnings(
        conn, job["organization_id"], code=code, period=period,
        rows=rows, fields=fields, label_col=label)


async def _fail(job_id: str, document_id, message: str) -> None:
    async with db.get_pool().acquire() as conn:
        await conn.execute(
            "update extraction_jobs set status='failed', finished_at=now(), error_message=$2 "
            "where id=$1::uuid",
            job_id, message,
        )
        await conn.execute(
            "update documents set status='uploaded' where id=$1", document_id
        )


async def enqueue_or_run(conn, document_version_id: str) -> str:
    """Создаёт extraction_job (или переиспользует) и возвращает его id."""
    row = await conn.fetchrow(
        "insert into extraction_jobs(document_version_id, status) "
        "values($1::uuid, 'queued') returning id",
        document_version_id,
    )
    return str(row["id"])
