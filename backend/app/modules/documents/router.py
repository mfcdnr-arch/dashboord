"""Модуль «Документы»: загрузка файлов в папки (MinIO) и их список.

Отчётная дата указывается вручную при загрузке (решение по проекту).
Форматы v1: xlsx, xls, csv, pdf, docx.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Optional

from asyncpg.exceptions import ForeignKeyViolationError
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool

from ... import db
from ..audit.service import write_event
from ..auth.deps import get_current_user, require_roles
from . import service as svc
from . import storage

log = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])
manage = require_roles("superadmin", "admin", "moderator")

MAX_DOCS_LIMIT = 200
# Размер и список форматов живут в service.py — их же применяет зона «Загрузка».


async def _read_capped(file, limit: int) -> bytes:
    """Читает UploadFile по частям; при превышении limit — HTTP 413."""
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf.extend(chunk)
        if len(buf) > limit:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"Файл слишком большой. Максимум {limit // (1024 * 1024)} МБ.",
            )
    return bytes(buf)


async def _folder_in_org(conn, folder_id: str, org_id) -> bool:
    return bool(
        await conn.fetchval(
            "select 1 from folders where id=$1::uuid and organization_id=$2",
            folder_id, org_id,
        )
    )


@router.post("/folders/{folder_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    folder_id: str,
    file: UploadFile = File(...),
    reporting_period_start: date = Form(...),
    reporting_period_end: Optional[date] = Form(None),
    force: bool = Form(False),
    user: dict = Depends(manage),
):
    """Загрузка файла в КОНКРЕТНУЮ папку (человек уже знает, куда кладёт).

    Сам путь сохранения общий с зоной «Загрузка» (`service.save_document`):
    проверка дублей, запись в хранилище и постановка распознавания должны быть
    одни и те же, иначе два входа в систему однажды повели бы себя по-разному.
    """
    filename = svc.safe_filename(file.filename)
    content = await _read_capped(file, svc.MAX_UPLOAD_BYTES)

    async with db.get_pool().acquire() as conn:
        if not await _folder_in_org(conn, folder_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Папка не найдена")
        try:
            return await svc.save_document(
                conn, org_id=user["organization_id"], user_id=user["id"], folder_id=folder_id,
                filename=filename, content=content, content_type=file.content_type,
                period_start=reporting_period_start, period_end=reporting_period_end, force=force)
        except svc.UploadError as e:
            raise HTTPException(e.status_code, e.detail)


async def _dataset_usage(conn, org_id, document_id: str) -> list:
    """Кто останется без источника, если снести выпуски этого документа.

    Опасен не сам выпуск, а исчезновение ПОСЛЕДНЕГО выпуска кода: виджеты и
    формулы ссылаются на датасет по коду, а не на конкретный выпуск. Пока у
    кода остаются другие выпуски (обычный случай — недельные формы), дашборд
    продолжит считаться по ним, и удаление одного файла ничего не ломает.
    """
    codes = await conn.fetch(
        "select r.code, count(*) as mine, "
        "  (select count(*) from dataset_releases a "
        "     where a.organization_id=$2 and a.code=r.code) as total "
        "from dataset_releases r "
        "join document_versions v on v.id = r.source_document_version_id "
        "where v.document_id=$1::uuid group by r.code", document_id, org_id)
    orphaned = [c["code"] for c in codes if c["mine"] >= c["total"]]
    if not orphaned:
        return []

    out: list = []
    widgets = await conn.fetch(
        "select w.name as widget, d.name as dash from widgets w "
        "join dashboards d on d.id = w.dashboard_id "
        "where w.organization_id=$1 and w.config->>'dataset_code' = any($2::text[])",
        org_id, orphaned)
    out += [f"виджет «{r['widget']}» на дашборде «{r['dash']}»" for r in widgets]

    # Формулы показателей: ссылка на датасет живёт внутри разобранного AST,
    # достаём её тем же кодом, что и проверка циклов в модуле метрик.
    from ..metrics.parser import extract_dependencies
    rows = await conn.fetch(
        "select m.code, m.name, mv.formula_ast from metric_versions mv "
        "join metrics m on m.id = mv.metric_id "
        "where m.organization_id=$1 and mv.formula_ast is not null and mv.status <> 'deprecated'", org_id)
    for r in rows:
        ast = r["formula_ast"]
        if isinstance(ast, str):
            ast = json.loads(ast)
        if set(extract_dependencies(ast)["datasets"]) & set(orphaned):
            label = f"показатель «{r['name']}» ({r['code']})"
            if label not in out:
                out.append(label)
    return out


@router.delete("/folders/{folder_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(folder_id: str, document_id: str, user: dict = Depends(manage),
                          with_data: bool = Query(False, description="удалить вместе с выпущенными данными")):
    """Удаление документа вместе с версиями и файлами в хранилище.

    По умолчанию отказываем, если из документа уже выпускали данные:
    `dataset_releases` ссылается на версию документа через
    `source_document_version_id` БЕЗ каскада, то есть это происхождение
    показателей — удалив документ молча, мы оборвали бы связь «цифра на
    дашборде → первичный файл», ради которой конвейер и построен.

    Но безусловный запрет оказался тупиком: ошибочно загруженный файл,
    из которого успели выпустить данные, оставался в системе НАВСЕГДА —
    удаления выпуска в системе нет вовсе. Поэтому есть осознанный выход:
    `with_data=true` сносит документ вместе с его выпусками. Это необратимо,
    поэтому доступно только суперадминистратору и только если на данные никто
    не опирается — иначе называем виновника поимённо.

    Порядок важен: сначала БД, потом файлы. При обратном порядке сбой в БД
    оставил бы документ без файла — он виден в списке, но не открывается.
    """
    async with db.get_pool().acquire() as conn:
        if not await _folder_in_org(conn, folder_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Папка не найдена")
        doc = await conn.fetchrow(
            "select id, original_filename from documents "
            "where id=$1::uuid and folder_id=$2::uuid and organization_id=$3",
            document_id, folder_id, user["organization_id"],
        )
        if not doc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Документ не найден")

        releases = await conn.fetchval(
            "select count(*) from dataset_releases r "
            "join document_versions v on v.id = r.source_document_version_id "
            "where v.document_id=$1::uuid",
            document_id,
        )
        if releases and not with_data:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Из документа уже выпущены данные (выпусков: {releases}) — удаление отменено. "
                "Иначе показатели на дашбордах потеряют связь с первичным файлом. "
                "Удалить вместе с данными может суперадминистратор.",
            )
        if releases and with_data:
            if "superadmin" not in set(user.get("roles") or ()):
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "Недостаточно прав: удалить документ вместе с выпущенными данными "
                    "может только суперадминистратор.",
                )
            used = await _dataset_usage(conn, user["organization_id"], document_id)
            if used:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Удаление отменено — на данные этого документа опираются: "
                    + "; ".join(used[:5]) + ". Уберите их или замените источник, потом удаляйте.",
                )

        paths = [
            r["storage_path"]
            for r in await conn.fetch(
                "select storage_path from document_versions where document_id=$1::uuid", document_id
            )
        ]
        try:
            async with conn.transaction():
                await write_event(
                    conn, user["organization_id"], user["id"], "delete", "document", document_id,
                    old_data={"original_filename": doc["original_filename"], "folder_id": folder_id,
                              "releases_deleted": releases if with_data else 0},
                )
                if releases and with_data:
                    # Значения и поля выпуска уходят каскадом (миграция 001);
                    # сами выпуски держат документ внешним ключом, поэтому их
                    # снимаем первыми, иначе удаление документа не пройдёт.
                    await conn.execute(
                        "delete from dataset_releases where id in ("
                        "  select r.id from dataset_releases r "
                        "  join document_versions v on v.id = r.source_document_version_id "
                        "  where v.document_id=$1::uuid)", document_id)
                await conn.execute("delete from documents where id=$1::uuid", document_id)
        except ForeignKeyViolationError as e:
            # Страховка на случай связи, о которой мы здесь не знаем: понятный
            # отказ вместо сырого 500 из драйвера.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Документ используется другими данными и не может быть удалён: {e}",
            )

    # Файлы удаляем после фиксации транзакции. Осечка здесь оставит «сироту» в
    # хранилище — это безобиднее, чем документ в списке без файла, поэтому
    # операцию не проваливаем, а сообщаем в лог.
    for p in paths:
        try:
            await run_in_threadpool(storage.remove_object, p)
        except Exception as e:
            log.warning("не удалось удалить объект хранилища %s: %s", p, e)


@router.get("/folders/{folder_id}/documents")
async def list_documents(
    folder_id: str,
    limit: int = Query(50, ge=1, le=MAX_DOCS_LIMIT),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
):
    """Постранично: {total, limit, offset, items}. Сортировка — новые сверху.

    Пагинация нужна, чтобы папка с тысячами документов не выгружалась целиком
    на каждый заход. Индексы ix_documents_folder_created / ix_document_versions_doc
    (миграция 022) держат запрос на диапазоне без полного скана.
    """
    async with db.get_pool().acquire() as conn:
        if not await _folder_in_org(conn, folder_id, user["organization_id"]):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Папка не найдена")
        total = await conn.fetchval(
            "select count(*) from documents where folder_id=$1::uuid", folder_id
        )
        rows = await conn.fetch(
            "select d.id, d.original_filename, d.source_type, d.status, "
            "d.reporting_period_start, d.reporting_period_end, d.created_at, "
            "v.id as version_id, v.file_size_bytes as size, "
            # Состояние конвейера: распознан ли файл, подошла ли разметка
            # прошлого выпуска, выпущены ли из него данные. Человек видит это
            # прямо в списке папки и заходит только туда, где нужен он сам.
            "j.status as job_status, j.template_match, j.template_note, "
            "(select count(*) from dataset_releases r "
            "   where r.source_document_version_id = v.id and r.status <> 'superseded') as releases, "
            # Выпущено человеком или автоматом — разные состояния для того, кто
            # смотрит папку: во втором случае он кнопку не нажимал и должен
            # понять, откуда взялись данные.
            "(select bool_or(r.auto_released) from dataset_releases r "
            "   where r.source_document_version_id = v.id and r.status <> 'superseded') as auto_released "
            "from documents d "
            "left join lateral (select id, file_size_bytes from document_versions v "
            "  where v.document_id=d.id order by version_no desc limit 1) v on true "
            "left join lateral (select status, template_match, template_note from extraction_jobs j "
            "  where j.document_version_id = v.id order by created_at desc limit 1) j on true "
            # Порядок — по ОТЧЁТНОЙ дате (свежие сверху), а не по времени загрузки:
            # формы загружают вразнобой, и список выглядел вперемешку. Документы без
            # отчётной даты уходят вниз, между собой — по времени загрузки.
            "where d.folder_id=$1::uuid "
            "order by d.reporting_period_start desc nulls last, d.created_at desc "
            "limit $2 offset $3",
            folder_id, limit, offset,
        )
    return {"total": total, "limit": limit, "offset": offset,
            "items": [_with_pipeline(dict(r)) for r in rows]}


def _with_pipeline(row: dict) -> dict:
    """Одно понятное состояние файла вместо трёх технических полей.

    Порядок проверок — от конца конвейера к началу: выпущенные данные важнее
    того, как файл распознавался, а «требует внимания» должно перекрывать
    «распознан», иначе человек решит, что файл готов.
    """
    job, match = row.get("job_status"), row.get("template_match")
    if row.get("releases"):
        if row.get("auto_released"):
            state = "released_auto"
            hint = ("Данные выпущены автоматически: форма совпала с прошлым отчётом и замечаний "
                    "к ней не было. Они уже считаются на дашбордах — проверьте цифры, и если "
                    "что-то не так, откройте файл и нажмите «Отменить выпуск».")
        else:
            state, hint = "released", "Данные выпущены и уже считаются на дашбордах."
    elif job in (None, "queued", "running"):
        state = "parsing" if job else "new"
        hint = "Идёт распознавание…" if job else "Файл ещё не распознавался."
    elif job == "failed":
        state, hint = "failed", "Распознать файл не удалось — откройте его и посмотрите причину."
    elif match == "exact":
        state, hint = "ready", row.get("template_note") or "Разметка подставится из прошлого выпуска."
    elif match == "structure_differs":
        state, hint = "attention", row.get("template_note") or "Форма отличается от прошлого выпуска."
    else:
        state, hint = "needs_markup", row.get("template_note") or "Файл распознан — разметьте и выпустите данные."
    row["pipeline"] = state
    row["pipeline_hint"] = hint
    return row
