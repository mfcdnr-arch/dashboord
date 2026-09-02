"""Модуль «Ingestion» (HTTP): запуск извлечения и просмотр результата.

- POST /document-versions/{version_id}/extract — поставить задачу извлечения;
- GET  /document-versions/{version_id}/extraction — последнее задание + результат;
- GET  /extraction-jobs/{job_id} — задание, распознанные таблицы и столбцы.

Правку разметки (границы/шапки/типы/маппинг) и выпуск датасета — этап 3.2.
"""
from __future__ import annotations

import json
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ... import db
from ..audit import service as audit_svc
from ..auth.deps import get_current_user, require_roles
from . import analyze, impact, mapping, queue, service

router = APIRouter(tags=["ingestion"])
manage = require_roles("superadmin", "admin", "moderator")


async def _version_in_org(conn, version_id: str, org_id) -> bool:
    return bool(
        await conn.fetchval(
            "select 1 from document_versions dv join documents d on d.id=dv.document_id "
            "where dv.id=$1::uuid and d.organization_id=$2",
            version_id, org_id,
        )
    )


async def _job_in_org(conn, job_id: str, org_id) -> bool:
    return bool(
        await conn.fetchval(
            "select 1 from extraction_jobs ej "
            "join document_versions dv on dv.id=ej.document_version_id "
            "join documents d on d.id=dv.document_id "
            "where ej.id=$1::uuid and d.organization_id=$2",
            job_id, org_id,
        )
    )


async def _object_in_org(conn, object_id: str, org_id) -> bool:
    return bool(
        await conn.fetchval(
            "select 1 from objects where id=$1::uuid and organization_id=$2",
            object_id, org_id,
        )
    )


@router.post("/document-versions/{version_id}/extract", status_code=status.HTTP_202_ACCEPTED)
async def start_extraction(version_id: str, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        if not await _version_in_org(conn, version_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Версия документа не найдена")
        job_id = await service.enqueue_or_run(conn, version_id)
    await queue.enqueue_extraction(job_id)
    return {"job_id": job_id, "status": "queued"}


async def _suggest_dataset_code(conn, version_id: str) -> str:
    """Код датасета по умолчанию — от имени объекта.

    Раньше в форме выпуска жёстко стояло `dataset`, одинаково для любого
    объекта. Код ищется по паре «организация + код» БЕЗ учёта объекта, поэтому
    второй объект с тем же кодом молча смешался бы с первым: выпуск за уже
    занятый период заместил бы чужой, а виджеты стали бы брать чужие данные.
    Подсказываем имя, производное от объекта, — столкновений не возникает.

    Если у объекта уже есть выпуски, предлагаем ИХ код: недельные формы одного
    объекта должны попадать в один ряд, а не начинать новый.
    """
    row = await conn.fetchrow(
        "select o.id as object_id, o.name as object_name from document_versions dv "
        "join documents d on d.id = dv.document_id "
        "join folders f on f.id = d.folder_id "
        "join objects o on o.id = f.object_id "
        "where dv.id=$1::uuid", version_id)
    if row is None:
        return "dataset"
    used = await conn.fetchval(
        "select code from dataset_releases where object_id=$1 and status <> 'superseded' "
        "order by created_at desc limit 1", row["object_id"])
    return used or analyze.slug(row["object_name"] or "dataset")


async def _job_payload(conn, job_id: str) -> dict:
    job = await conn.fetchrow(
        "select id, document_version_id, status, engine, started_at, finished_at, "
        "error_message, confidence_score, warnings, created_at "
        "from extraction_jobs where id=$1::uuid",
        job_id,
    )
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задание извлечения не найдено")
    tables = await conn.fetch(
        "select id, sheet_or_page, table_index, row_count, column_count, header_rows, "
        "raw_preview, merges, data_rect "
        "from extracted_tables where extraction_job_id=$1::uuid order by table_index",
        job_id,
    )
    out_tables = []
    for t in tables:
        cols = await conn.fetch(
            "select column_index, source_header, inferred_type, confidence_score, canonical_field_code "
            "from extracted_columns where extracted_table_id=$1 order by column_index",
            t["id"],
        )
        out_tables.append({
            "id": str(t["id"]),
            "sheet_or_page": t["sheet_or_page"],
            "table_index": t["table_index"],
            "row_count": t["row_count"],
            "column_count": t["column_count"],
            "header_rows": t["header_rows"],
            "preview": json.loads(t["raw_preview"]) if t["raw_preview"] else [],
            # объединения и область данных — чтобы предпросмотр рисовался
            # rowspan/colspan один-в-один с оригиналом
            "merges": json.loads(t["merges"]) if t["merges"] else [],
            "data_rect": json.loads(t["data_rect"]) if t["data_rect"] else None,
            "columns": [dict(c) for c in cols],
        })
    # Разметка прошлого выпуска этой же формы: если структура совпала, конструктор
    # откроется уже размеченным. Не совпала — шаблон приходит с пометкой, что
    # применить его нельзя (чужая разметка молча дала бы неверные цифры).
    ctx = await mapping.resolve_context(conn, job_id)
    template = None
    if ctx is not None and ctx["object_id"] is not None:
        template = await mapping.layout_template_for_tables(
            conn, ctx["object_id"], [t["id"] for t in out_tables])

    return {
        "job_id": str(job["id"]),
        "layout_template": template,
        "suggested_code": await _suggest_dataset_code(conn, str(job["document_version_id"])),
        "document_version_id": str(job["document_version_id"]),
        "status": job["status"],
        "engine": job["engine"],
        "confidence_score": float(job["confidence_score"]) if job["confidence_score"] is not None else None,
        "warnings": json.loads(job["warnings"]) if job["warnings"] else [],
        "error_message": job["error_message"],
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "tables": out_tables,
    }


@router.get("/extraction-jobs/{job_id}")
async def get_job(job_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        owns = await conn.fetchval(
            "select 1 from extraction_jobs ej "
            "join document_versions dv on dv.id=ej.document_version_id "
            "join documents d on d.id=dv.document_id "
            "where ej.id=$1::uuid and d.organization_id=$2",
            job_id, user["organization_id"],
        )
        if not owns:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Задание извлечения не найдено")
        return await _job_payload(conn, job_id)


@router.get("/document-versions/{version_id}/extraction")
async def get_latest_for_version(version_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        if not await _version_in_org(conn, version_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Версия документа не найдена")
        job_id = await conn.fetchval(
            "select id from extraction_jobs where document_version_id=$1::uuid "
            "order by created_at desc limit 1",
            version_id,
        )
        if job_id is None:
            return {"status": "none", "tables": []}
        return await _job_payload(conn, str(job_id))


# --------------------------------------------------------------------------- #
# Маппинг и выпуск датасета (этап 3.2)
# --------------------------------------------------------------------------- #
class FieldMap(BaseModel):
    column_index: int
    field_code: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    data_type: str = "text"  # number | date | text
    unit: Optional[str] = None
    is_row_label: bool = False


class LayoutIn(BaseModel):
    """Что пользователь выделил в конструкторе разметки."""

    data_rect: Optional[List[int]] = None  # [r1, c1, r2, c2], границы включительно
    header_rows: Optional[int] = Field(default=None, ge=0, le=20)
    orientation: str = "columns"  # columns — показатели в столбцах; rows — в строках
    skip_rows: List[int] = Field(default_factory=list)


class CellPick(BaseModel):
    """Отдельная ячейка как показатель (координаты исходной сетки)."""

    row: int = Field(ge=0)
    col: int = Field(ge=0)
    field_code: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    data_type: str = "number"


class LayoutPreviewIn(LayoutIn):
    table_id: str


class ReleaseIn(BaseModel):
    table_id: str
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    reporting_period_start: Optional[date] = None
    reporting_period_end: Optional[date] = None
    fields: List[FieldMap] = Field(default_factory=list)
    layout: Optional[LayoutIn] = None
    cells: List[CellPick] = Field(default_factory=list)
    supersede: bool = False


class ReleaseBySheetIn(BaseModel):
    """Книга, где ЛИСТ = отчётная дата.

    `year` обязателен: на листах госформ пишут «17.08» без года, и подставлять
    его по имени файла — гадание, а ошибка тихо создаёт выпуски не того года.
    `since` — глубина истории: книга за девять месяцев даёт 189 дат, и грузить
    их все нужно далеко не всегда.
    """
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    year: int = Field(ge=2000, le=2100)
    since: Optional[date] = None
    layout: Optional[LayoutIn] = None
    # Подписи строк, которые НЕ являются строками данных: в ежедневном отчёте
    # под таблицей три блока итогов («Принято/Выдано/Отказ», «На вчера»,
    # «Накопительный»), и приняв их за отделения, суммы утроились бы.
    exclude_row_labels: List[str] = Field(default_factory=list)
    supersede: bool = False


class CanonicalFieldIn(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    data_type: str = "text"
    unit: Optional[str] = None
    is_row_label: bool = False
    description: Optional[str] = None


@router.get("/extraction-jobs/{job_id}/tables/{table_id}/mapping-suggestion")
async def mapping_suggestion(job_id: str, table_id: str, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        ctx = await mapping.resolve_context(conn, job_id)
        if ctx is None or ctx["organization_id"] != user["organization_id"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Задание извлечения не найдено")
        owns_table = await conn.fetchval(
            "select 1 from extracted_tables where id=$1::uuid and extraction_job_id=$2::uuid",
            table_id, job_id,
        )
        if not owns_table:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Таблица не найдена в задании")
        return await mapping.suggest_mapping(conn, table_id, ctx["object_id"])


@router.post("/extraction-jobs/{job_id}/layout-preview")
async def layout_preview(job_id: str, body: LayoutPreviewIn, user: dict = Depends(manage)):
    """Пересчёт разметки под выбор мышью: заголовки, типы, строки-образцы.

    Считает тот же код, что и выпуск, поэтому предпросмотр «что получится»
    не может разойтись с тем, что реально уедет в датасет.
    """
    async with db.get_pool().acquire() as conn:
        ctx = await mapping.resolve_context(conn, job_id)
        if ctx is None or ctx["organization_id"] != user["organization_id"]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Задание извлечения не найдено")
        owns_table = await conn.fetchval(
            "select 1 from extracted_tables where id=$1::uuid and extraction_job_id=$2::uuid",
            body.table_id, job_id,
        )
        if not owns_table:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Таблица не найдена в задании")
        try:
            return await mapping.layout_preview(
                conn, body.table_id, ctx["object_id"],
                data_rect=body.data_rect, header_rows=body.header_rows,
                orientation=body.orientation, skip_rows=body.skip_rows,
            )
        except ValueError as err:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(err))


async def _rows_for_release(conn, job_id: str, body: "ReleaseIn", org_id):
    """Строки и поля так, как их увидит выпуск. Общий разбор для проверки
    качества и предпросмотра последствий — иначе два экрана перед одной
    кнопкой читали бы файл по-разному."""
    ctx = await mapping.resolve_context(conn, job_id)
    if ctx is None or ctx["organization_id"] != org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задание извлечения не найдено")
    table = await conn.fetchrow(
        "select header_rows, data, merges, data_rect from extracted_tables "
        "where id=$1::uuid and extraction_job_id=$2::uuid", body.table_id, job_id)
    if table is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Таблица не найдена в задании")

    grid = json.loads(table["data"]) if table["data"] else []
    merges = [tuple(m) for m in (json.loads(table["merges"]) if table["merges"] else [])]
    lay = {**mapping.DEFAULT_LAYOUT, **(body.layout.model_dump() if body.layout else {})}
    rect = lay["data_rect"] or (json.loads(table["data_rect"]) if table["data_rect"] else None)
    hdr = int((table["header_rows"] if lay["header_rows"] is None else lay["header_rows"]) or 0)
    area = mapping.analysis_grid(grid, merges, rect, lay["orientation"])
    rows = mapping.data_rows(area, hdr, lay["skip_rows"] or [])
    fields = [f.model_dump() for f in body.fields]
    label = next((f["column_index"] for f in fields if f.get("is_row_label")), None)
    return rows, fields, label


@router.post("/extraction-jobs/{job_id}/release-impact")
async def release_impact(job_id: str, body: ReleaseIn, user: dict = Depends(manage)):
    """Что изменится на дашбордах, если выпустить эти данные (п. 15).

    Отвечает на три вопроса разом: что станет с цифрами, где это увидят и что
    может сломаться (графа или строка исчезла, а виджеты на неё ссылаются).
    Свёртка строк — та же, что у карточки показателя, поэтому обещанное здесь
    число совпадёт с тем, что появится на дашборде.
    """
    async with db.get_pool().acquire() as conn:
        rows, fields, label = await _rows_for_release(conn, job_id, body, user["organization_id"])
        return await impact.release_impact(
            conn, user["organization_id"], code=body.code,
            period=body.reporting_period_start, rows=rows, fields=fields, label_col=label)


@router.post("/extraction-jobs/{job_id}/quality-check")
async def quality_check(job_id: str, body: ReleaseIn, user: dict = Depends(manage)):
    """Замечания по качеству ДО выпуска: сверка с предыдущей неделей.

    Считает та же функция, что и выпуск, поэтому «перед выпуском было чисто, а
    после появились замечания» невозможно. Отдельный маршрут, а не часть
    предпросмотра разметки: предпросмотр дёргается на каждое движение мышью, а
    здесь нужен ещё и код датасета, который человек задаёт в форме выпуска.
    """
    async with db.get_pool().acquire() as conn:
        rows, fields, label = await _rows_for_release(conn, job_id, body, user["organization_id"])
        warnings = await mapping.quality_warnings(
            conn, user["organization_id"], code=body.code, period=body.reporting_period_start,
            rows=rows, fields=fields, label_col=label)
    return {"warnings": warnings, "ok": not warnings}


@router.post("/extraction-jobs/{job_id}/release", status_code=status.HTTP_201_CREATED)
async def create_release(job_id: str, body: ReleaseIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        if not await _job_in_org(conn, job_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Задание извлечения не найдено")
        try:
            async with conn.transaction():
                res = await mapping.build_release(
                    conn, job_id=job_id, table_id=body.table_id, code=body.code,
                    name=body.name, reporting_period_start=body.reporting_period_start,
                    reporting_period_end=body.reporting_period_end,
                    fields=[f.model_dump() for f in body.fields],
                    layout=body.layout.model_dump() if body.layout else None,
                    cells=[c.model_dump() for c in body.cells],
                    supersede=body.supersede, user=user,
                )
                # Создание выпуска пишется в журнал наравне с автоматическим:
                # после него меняются цифры на дашбордах, и вопрос «кто это
                # сделал» должен иметь ответ независимо от того, нажали кнопку
                # или сработал автомат.
                await audit_svc.write_event(
                    conn, user["organization_id"], user["id"], "create", "dataset_release",
                    res["release_id"],
                    new_data={"code": body.code, "period": str(body.reporting_period_start),
                              "auto": False, "values": res.get("values_count"),
                              "rows": res.get("rows"),
                              "superseded": res.get("superseded_release_id")})
                return res
        except mapping.ReleaseConflict as conflict:
            # Отказ должен объяснять ПРИЧИНУ и показывать выход. Раньше он
            # сообщал только факт, и человек, который сам ничего не выпускал,
            # видел «уже существует» и читал это как поломку.
            auto = bool(conflict.existing.get("auto"))
            msg = ("Данные за этот период уже выпущены автоматически — форма совпала с прошлым "
                   "отчётом, и замечаний к ней не было. Проверьте цифры; если нужна ваша "
                   "разметка — отметьте «Заместить», прежний выпуск будет снят с использования."
                   if auto else
                   "Выпуск за этот период уже существует. Чтобы заменить его своей разметкой, "
                   "отметьте «Заместить» — прежний выпуск будет снят с использования.")
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"message": msg, "existing": conflict.existing},
            )
        except ValueError as err:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(err))


@router.get("/objects/{object_id}/canonical-fields")
async def list_canonical_fields(object_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        if not await _object_in_org(conn, object_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
        rows = await conn.fetch(
            "select code, name, data_type, unit, is_row_label, description "
            "from canonical_fields where object_id=$1::uuid order by name",
            object_id,
        )
    return [dict(r) for r in rows]


@router.post("/objects/{object_id}/canonical-fields", status_code=status.HTTP_201_CREATED)
async def create_canonical_field(object_id: str, body: CanonicalFieldIn, user: dict = Depends(manage)):
    async with db.get_pool().acquire() as conn:
        if not await _object_in_org(conn, object_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
        exists = await conn.fetchval(
            "select 1 from canonical_fields where object_id=$1::uuid and code=$2",
            object_id, body.code,
        )
        if exists:
            raise HTTPException(status.HTTP_409_CONFLICT, "Поле с таким кодом уже есть")
        row = await conn.fetchrow(
            "insert into canonical_fields(object_id, code, name, data_type, unit, is_row_label, description, created_by) "
            "values($1::uuid,$2,$3,$4,$5,$6,$7,$8) returning code, name, data_type, unit, is_row_label, description",
            object_id, body.code, body.name, body.data_type, body.unit,
            body.is_row_label, body.description, user["id"],
        )
    return dict(row)


@router.post("/extraction-jobs/{job_id}/release-by-sheet",
             status_code=status.HTTP_201_CREATED)
async def create_releases_by_sheet(job_id: str, body: ReleaseBySheetIn,
                                   user: dict = Depends(manage)):
    """Выпуск на каждый лист книги. Отдаёт построчный отчёт: что создано, что
    пропущено и почему.

    Отдельным эндпоинтом, а не флагом обычного выпуска: у того один лист, одна
    дата и один ответ, а здесь их десятки, и человеку нужно видеть судьбу
    КАЖДОГО листа — иначе «загружено» скрывает, что половина дат отвалилась.
    """
    async with db.get_pool().acquire() as conn:
        if not await _job_in_org(conn, job_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Задание извлечения не найдено")
        try:
            async with conn.transaction():
                res = await mapping.build_releases_by_sheet(
                    conn, job_id=job_id, code=body.code, name=body.name,
                    year=body.year, user=user, since=body.since,
                    layout=body.layout.model_dump() if body.layout else None,
                    exclude_row_labels=body.exclude_row_labels,
                    supersede=body.supersede)
                # В журнал — одно событие на загрузку, а не на каждый лист:
                # это одно решение человека, и в ленте аудита полсотни записей
                # об одном нажатии кнопки только мешают.
                await audit_svc.write_event(
                    conn, user["organization_id"], user["id"], "create", "dataset_release",
                    job_id,
                    new_data={"code": body.code, "by_sheet": True, "year": body.year,
                              "sheets": res["sheets"], "released": res["released"],
                              "skipped": len(res["skipped"]), "failed": len(res["failed"])})
                return res
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.get("/objects/{object_id}/dataset-releases")
async def list_releases(object_id: str, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        if not await _object_in_org(conn, object_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Объект не найден")
        rows = await conn.fetch(
            "select id, code, name, status, reporting_period_start, reporting_period_end, "
            "validated_at, created_at, superseded_by_release_id, "
            "(select count(*) from dataset_values dv where dv.dataset_release_id=r.id) as values_count "
            "from dataset_releases r where object_id=$1::uuid order by reporting_period_start desc nulls last, created_at desc",
            object_id,
        )
    return [dict(r) for r in rows]


@router.get("/dataset-releases/{release_id}")
async def get_release(release_id: str, limit: int = 200, user: dict = Depends(get_current_user)):
    async with db.get_pool().acquire() as conn:
        rel = await conn.fetchrow(
            "select id, code, name, status, object_id, reporting_period_start, reporting_period_end, "
            "validated_at, created_at, superseded_by_release_id "
            "from dataset_releases where id=$1::uuid and organization_id=$2",
            release_id, user["organization_id"],
        )
        if rel is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Выпуск датасета не найден")
        fields = await conn.fetch(
            "select canonical_field_code, extracted_column_id from dataset_release_fields "
            "where dataset_release_id=$1::uuid",
            release_id,
        )
        values = await conn.fetch(
            "select row_index, row_label, canonical_field_code, value_text, value_number, value_date "
            "from dataset_values where dataset_release_id=$1::uuid "
            "order by row_index limit $2",
            release_id, limit,
        )
    return {
        "release": dict(rel),
        "fields": [dict(f) for f in fields],
        "values": [dict(v) for v in values],
    }


# --------------------------------------------------------------------------- #
# Отмена выпуска: снять данные с использования, не трогая сам файл
# --------------------------------------------------------------------------- #
# Статус `superseded` заложен в схеме с самого начала и уважается ВСЕМИ
# чтениями (виджеты, метрики, предложения — везде `status <> 'superseded'`),
# но выставлялся только автоматически, когда за тот же период выпускали
# заново. Ручной отмены не было: единственным способом убрать ошибочные
# данные оставалось удаление самого документа, чего пользователь как раз
# делать не хочет — файл нужен, неверен только выпуск.
async def _release_usage(conn, org_id, release_id: str) -> list:
    """Кто останется без данных, если снять этот выпуск с использования.

    Значение имеет не выпуск сам по себе, а исчезновение ПОСЛЕДНЕГО активного
    выпуска кода: виджеты и формулы ссылаются на датасет по коду. Пока у кода
    остаются другие активные выпуски, отмена одного ничего не ломает.
    """
    row = await conn.fetchrow(
        "select code, (select count(*) from dataset_releases a "
        "   where a.organization_id=$2 and a.code=r.code and a.status<>'superseded' and a.id<>r.id) as others "
        "from dataset_releases r where r.id=$1::uuid and r.organization_id=$2", release_id, org_id)
    if row is None or row["others"]:
        return []
    code = row["code"]
    out: list = []
    widgets = await conn.fetch(
        "select w.name as widget, d.name as dash from widgets w "
        "join dashboards d on d.id = w.dashboard_id "
        "where w.organization_id=$1 and w.config->>'dataset_code' = $2", org_id, code)
    out += [f"виджет «{r['widget']}» на дашборде «{r['dash']}»" for r in widgets]

    from ..metrics.parser import extract_dependencies
    rows = await conn.fetch(
        "select m.code, m.name, mv.formula_ast from metric_versions mv "
        "join metrics m on m.id = mv.metric_id "
        "where m.organization_id=$1 and mv.formula_ast is not null and mv.status <> 'deprecated'", org_id)
    for r in rows:
        ast = r["formula_ast"]
        if isinstance(ast, str):
            ast = json.loads(ast)
        if code in extract_dependencies(ast)["datasets"]:
            label = f"показатель «{r['name']}» ({r['code']})"
            if label not in out:
                out.append(label)
    return out


async def _release_or_404(conn, release_id: str, org_id):
    rel = await conn.fetchrow(
        "select id, code, name, status, reporting_period_start from dataset_releases "
        "where id=$1::uuid and organization_id=$2", release_id, org_id)
    if rel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Выпуск датасета не найден")
    return rel


@router.post("/dataset-releases/{release_id}/cancel")
async def cancel_release(release_id: str, user: dict = Depends(manage)):
    """Снять выпуск с использования (статус `superseded`).

    Данные остаются в базе, файл не трогаем — операция ОБРАТИМА, поэтому
    отказом не блокируем даже если на датасет кто-то опирается: иначе человек
    с ошибочными цифрами на дашборде оказался бы заперт. Вместо запрета
    возвращаем список затронутого, чтобы он видел последствия.
    """
    async with db.get_pool().acquire() as conn:
        rel = await _release_or_404(conn, release_id, user["organization_id"])
        if rel["status"] == "superseded":
            raise HTTPException(status.HTTP_409_CONFLICT, "Выпуск уже снят с использования")
        affected = await _release_usage(conn, user["organization_id"], release_id)
        async with conn.transaction():
            await conn.execute(
                "update dataset_releases set status='superseded' where id=$1::uuid", release_id)
            await audit_svc.write_event(
                conn, user["organization_id"], user["id"], "update", "dataset_release", release_id,
                old_data={"status": rel["status"]},
                new_data={"status": "superseded", "code": rel["code"], "affected": affected})
    return {"status": "superseded", "affected": affected}


@router.post("/dataset-releases/{release_id}/restore")
async def restore_release(release_id: str, user: dict = Depends(manage)):
    """Вернуть снятый выпуск в работу."""
    async with db.get_pool().acquire() as conn:
        rel = await _release_or_404(conn, release_id, user["organization_id"])
        if rel["status"] != "superseded":
            raise HTTPException(status.HTTP_409_CONFLICT, "Выпуск и так в работе")
        async with conn.transaction():
            await conn.execute(
                "update dataset_releases set status='validated' where id=$1::uuid", release_id)
            await audit_svc.write_event(
                conn, user["organization_id"], user["id"], "update", "dataset_release", release_id,
                old_data={"status": "superseded"}, new_data={"status": "validated", "code": rel["code"]})
    return {"status": "validated"}


@router.delete("/dataset-releases/{release_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_release(release_id: str, user: dict = Depends(require_roles("superadmin"))):
    """Удалить выпуск вместе со значениями, оставив документ на месте.

    В отличие от отмены — необратимо, поэтому только суперадминистратору и с
    отказом, если после удаления у кода не останется активных выпусков, а на
    него опираются виджеты или формулы.
    """
    async with db.get_pool().acquire() as conn:
        await _release_or_404(conn, release_id, user["organization_id"])
        used = await _release_usage(conn, user["organization_id"], release_id)
        if used:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Удаление отменено — на эти данные опираются: " + "; ".join(used[:5])
                + ". Снимите выпуск с использования или уберите зависимости.")
        async with conn.transaction():
            await audit_svc.write_event(
                conn, user["organization_id"], user["id"], "delete", "dataset_release", release_id, old_data=None)
            # значения и поля выпуска уходят каскадом (миграция 001)
            await conn.execute("delete from dataset_releases where id=$1::uuid", release_id)


@router.get("/document-versions/{version_id}/dataset-releases")
async def list_version_releases(version_id: str, user: dict = Depends(get_current_user)):
    """Выпуски, сделанные из этой версии документа — чтобы человек видел их
    там же, где смотрит сам файл, и мог снять ошибочный с использования."""
    async with db.get_pool().acquire() as conn:
        rows = await conn.fetch(
            "select r.id, r.code, r.name, r.status, r.reporting_period_start, r.created_at, "
            "  r.auto_released, "
            "  (select count(*) from dataset_values dv where dv.dataset_release_id=r.id) as values_count "
            "from dataset_releases r "
            "where r.source_document_version_id=$1::uuid and r.organization_id=$2 "
            "order by r.created_at desc", version_id, user["organization_id"])
    return [dict(r) for r in rows]
