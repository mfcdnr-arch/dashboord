"""HTTP: виджеты страницы (список/данные/экспорт) + виджеты (CRUD/предпросмотр/
подсказки/данные/drill). Вынесено из router.py.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from ... import db
from ..audit import service as audit_svc
from ..auth.deps import get_current_user
from . import service
from ._router_base import _bad, manage
from .service import DashboardError

router = APIRouter()


class WidgetIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    widget_type: str
    config: Dict[str, Any] = {}
    position_x: int = 0
    position_y: int = 0
    width: int = 4
    height: int = 3


class WidgetPatch(BaseModel):
    name: Optional[str] = None
    widget_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    position_x: Optional[int] = None
    position_y: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None


class WidgetPreviewIn(BaseModel):
    widget_type: str
    name: Optional[str] = None
    config: Dict[str, Any] = {}


def _attachment(filename: str) -> str:
    """Заголовок вложения с ИМЕНЕМ ВИДЖЕТА, а не «widget.xlsx».

    Имена у нас русские, а в `filename=` можно только ASCII, поэтому по RFC 5987
    отдаём оба варианта: ASCII-запасной для старых программ и `filename*` с
    процентным кодированием для остальных. Из имени убираем то, что файловые
    системы не примут (слеши, двоеточия, кавычки), — иначе браузер сохранит
    файл со сломанным именем или откажется вовсе.
    """
    from urllib.parse import quote

    clean = re.sub(r'[\\/:*?"<>|\r\n]+', " ", filename).strip() or "widget.xlsx"
    clean = clean[:120]
    # Русское имя целиком выпадает из ASCII, и запасной вариант превращался в
    # «.xlsx» — то есть в скрытый файл без имени. Пусто — берём осмысленное
    # общее имя; современные браузеры всё равно возьмут filename* с кириллицей.
    stem, dot, ext = clean.rpartition(".")
    ascii_stem = (stem or clean).encode("ascii", "ignore").decode().strip()
    ascii_name = f"{ascii_stem}.{ext}" if ascii_stem and dot else "widget.xlsx"
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(clean)}'


# --- Виджеты страницы ---
# Выгрузка ОДНОГО виджета (п. 7): человеку, которому нужна одна таблица для
# доклада, не должен приезжать файл на семнадцать листов. Фильтры страницы
# передаются сюда же — файл обязан совпадать с тем, что человек видел.
# «Паспорт цифры» (п. 17): как графа менялась по неделям, из какого файла
# пришло значение и кто его выпустил. Ответ собирается из происхождения
# данных, а не из отдельного журнала — второй источник правды разошёлся бы.
@router.get("/widgets/{widget_id}/passport")
async def widget_passport(widget_id: str, user: dict = Depends(get_current_user),
                          field: Optional[str] = None, row: Optional[str] = None):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.widget_passport(conn, user["organization_id"], widget_id,
                                                 user, field=field, row=row)
        except DashboardError as e:
            raise _bad(e)


@router.get("/widgets/{widget_id}/export.xlsx")
async def export_widget_xlsx(widget_id: str, user: dict = Depends(get_current_user),
                             from_date: Optional[str] = None, to_date: Optional[str] = None,
                             row: Optional[str] = None):
    async with db.acquire(user["id"]) as conn:
        try:
            data, name = await service.export_widget_xlsx(
                conn, user["organization_id"], user, widget_id, from_date, to_date, row)
        except DashboardError as e:
            raise _bad(e)
        await audit_svc.write_event(conn, user["organization_id"], user["id"], "export",
                                    "widget", widget_id, new_data={"format": "xlsx"})
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _attachment(f"{name}.xlsx")},
    )


@router.get("/dashboard-pages/{page_id}/export.xlsx")
async def export_page_xlsx(page_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            data = await service.export_page_xlsx(conn, user["organization_id"], user, page_id)
        except DashboardError as e:
            raise _bad(e)
        # Для отчёта активности пользователя (волна B) — кто что выгружал.
        await audit_svc.write_event(conn, user["organization_id"], user["id"], "export",
                                    "dashboard_page", page_id, new_data={"format": "xlsx"})
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="dashboard-page.xlsx"'},
    )


@router.post("/dashboard-pages/{page_id}/fit-layout")
async def fit_layout(page_id: str, user: dict = Depends(manage)):
    """Подогнать размеры виджетов страницы под их тип (состав не меняется)."""
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.fit_page_layout(conn, user["organization_id"], page_id)
        except DashboardError as e:
            raise _bad(e)


@router.get("/dashboard-pages/{page_id}/widgets")
async def list_widgets(page_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.list_page_widgets(conn, user["organization_id"], page_id, user)
        except DashboardError as e:
            raise _bad(e)


@router.get("/dashboard-pages/{page_id}/data")
async def page_data(page_id: str, user: dict = Depends(get_current_user),
                    from_: Optional[str] = Query(None, alias="from"),
                    to: Optional[str] = Query(None),
                    row: Optional[str] = Query(None)):
    """Данные всех виджетов страницы за 1 запрос (перф). Учитывает фильтры страницы."""
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.compute_page_data(conn, user["organization_id"], page_id, user, from_, to, row)
        except DashboardError as e:
            raise _bad(e)


@router.get("/dashboard-pages/{page_id}/row-rank")
async def page_row_rank(page_id: str, row: str = Query(...),
                        user: dict = Depends(get_current_user),
                        from_: Optional[str] = Query(None, alias="from"),
                        to: Optional[str] = Query(None)):
    """Место выбранной строки среди остальных — содержимое drill-down по строке."""
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.page_row_rank(conn, user["organization_id"], page_id, row, user, from_, to)
        except DashboardError as e:
            raise _bad(e)


@router.get("/dashboard-pages/{page_id}/report-dates")
async def page_report_dates(page_id: str, user: dict = Depends(get_current_user)):
    """Отчётные даты страницы — список для выбора конкретного отчёта фильтром."""
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.page_report_dates(conn, user["organization_id"], page_id, user)
        except DashboardError as e:
            raise _bad(e)


@router.get("/dashboard-pages/{page_id}/summary")
async def page_summary(page_id: str, user: dict = Depends(get_current_user)):
    """«Как дела»: что выросло и что просело к прошлому отчёту."""
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.page_summary(conn, user["organization_id"], page_id, user)
        except DashboardError as e:
            raise _bad(e)


@router.get("/dashboard-pages/{page_id}/attention")
async def page_attention(page_id: str, user: dict = Depends(get_current_user)):
    """«На что посмотреть»: замечания к данным страницы (те же проверки качества,
    что видит модератор при выпуске)."""
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.page_attention(conn, user["organization_id"], page_id, user)
        except DashboardError as e:
            raise _bad(e)


@router.post("/dashboard-pages/{page_id}/widgets", status_code=status.HTTP_201_CREATED)
async def create_widget(page_id: str, body: WidgetIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.create_widget(
                conn, user["organization_id"], user["id"], page_id, body.name, body.widget_type,
                body.config, {"position_x": body.position_x, "position_y": body.position_y,
                              "width": body.width, "height": body.height})
        except DashboardError as e:
            raise _bad(e)


# --- Виджеты ---
@router.post("/widgets/preview")
async def preview_widget(body: WidgetPreviewIn, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.preview_widget(conn, user["organization_id"], body.widget_type, body.name, body.config)
        except DashboardError as e:
            raise _bad(e)


@router.get("/widgets/suggestions")
async def widget_suggestions(dataset_code: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.suggest_widgets(conn, user["organization_id"], dataset_code)
        except DashboardError as e:
            raise _bad(e)


# Регистрируется ДО параметризованных /widgets/{...}: конкретный путь, попавший
# после шаблона, перехватывается им (уже наступали на это с /audit/access).
@router.get("/widgets/problem-kinds")
async def problem_kinds(user: dict = Depends(get_current_user)):
    """Виды проблем для кнопки «сообщить о проблеме» — список задаёт сервер,
    чтобы подписи в интерфейсе и в тексте обращения не разошлись."""
    return {"kinds": [{"code": k, "label": v} for k, v in service.PROBLEM_KINDS.items()]}


@router.patch("/widgets/{widget_id}")
async def update_widget(widget_id: str, body: WidgetPatch, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.update_widget(conn, user["organization_id"], widget_id,
                                               body.model_dump(exclude_none=True))
        except DashboardError as e:
            raise _bad(e)


@router.delete("/widgets/{widget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_widget(widget_id: str, user: dict = Depends(manage)):
    async with db.acquire(user["id"]) as conn:
        try:
            await service.delete_widget(conn, user["organization_id"], widget_id)
        except DashboardError as e:
            raise _bad(e)


@router.get("/widgets/{widget_id}/data")
async def widget_data(widget_id: str, user: dict = Depends(get_current_user),
                      from_: Optional[str] = Query(None, alias="from"),
                      to: Optional[str] = Query(None),
                      row: Optional[str] = Query(None)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.compute_widget_data(conn, user["organization_id"], widget_id, from_, to, row, user)
        except DashboardError as e:
            raise _bad(e)


@router.get("/widgets/{widget_id}/related")
async def widget_related(widget_id: str, user: dict = Depends(get_current_user)):
    """Куда можно перейти от этой цифры (п. 1). Пункты строятся по данным —
    из формул и настроек виджетов, а не из настроенных руками связок: те
    устаревают молча и ведут в никуда."""
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.widget_related(conn, user["organization_id"], user, widget_id)
        except DashboardError as e:
            raise _bad(e)


class ProblemIn(BaseModel):
    kind: str = "other"
    comment: Optional[str] = Field(None, max_length=2000)


@router.post("/widgets/{widget_id}/report-problem", status_code=status.HTTP_201_CREATED)
async def report_problem(widget_id: str, body: ProblemIn, user: dict = Depends(get_current_user)):
    """Жалоба на конкретную цифру (п. 15). Контекст — дашборд, страница,
    показатель и текущее значение — собирает сервер: человек не должен
    объяснять словами, где именно он это увидел."""
    from ..appeals.service import AppealsRateLimited
    async with db.acquire(user["id"]) as conn:
        try:
            async with conn.transaction():
                return await service.report_widget_problem(
                    conn, user["organization_id"], user, widget_id, body.kind, body.comment)
        except AppealsRateLimited as e:
            # Потолок на новые обращения общий с «Кабинетом»: одна кнопка не
            # должна обходить ограничение другой.
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e))
        except DashboardError as e:
            raise _bad(e)


@router.get("/widgets/{widget_id}/drill")
async def widget_drill(widget_id: str, user: dict = Depends(get_current_user)):
    async with db.acquire(user["id"]) as conn:
        try:
            return await service.widget_drill(conn, user["organization_id"], widget_id, user)
        except DashboardError as e:
            raise _bad(e)
