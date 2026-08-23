"""Паспорт цифры (п. 17 списка предложений): откуда взялось это число.

На дашборде видно ЗНАЧЕНИЕ, а вопросы у человека три и все про происхождение:
как оно менялось по неделям, из какого файла пришло и кто его выпустил. До сих
пор ответ собирался вручную — «Динамика» показывала ряд, аналитика папки
называла файлы, журнал аудита знал автора, и всё это в разных местах.

Считаем ТЕМ ЖЕ правилом свёртки строк, что и карточка показателя
(`aggregate_series`): паспорт обязан объяснять ту цифру, которая на экране, а
не похожую на неё.
"""
from __future__ import annotations

from typing import Optional

from ._aggregate import aggregate_series
from ._alerts import _cfg
from ._base import DashboardError
from ._rls import _can_view, visible_widget_ids
from ._rowrls import allowed_rows_for_dataset
from ._widgetsources import _row_acl_clause, _widget_org


async def widget_passport(conn, org_id, widget_id: str, user: dict,
                          field: Optional[str] = None, row: Optional[str] = None) -> dict:
    """История графы за все выпуски: значение, файл, кто и когда выпустил.

    Замещённые выпуски показываем ТОЖЕ и помечаем: если цифра за неделю
    менялась, человек должен видеть, что её заместили, — иначе «было 891 651,
    стало 900 000» выглядит ошибкой системы, а не повторным выпуском.

    RLS: доступ к дашборду и whitelist виджетов проверяются до расчёта, строки
    сворачиваются только разрешённые этому человеку.
    """
    w = await _widget_org(conn, org_id, widget_id)
    if w is None:
        raise DashboardError("Виджет не найден")
    if not await _can_view(conn, org_id, user, str(w["dashboard_id"])):
        raise DashboardError("Виджет не найден")
    allowed_w = await visible_widget_ids(conn, org_id, user, str(w["dashboard_id"]))
    if allowed_w is not None and widget_id not in allowed_w:
        raise DashboardError("Виджет не найден")

    cfg = _cfg(w)
    code = cfg.get("dataset_code")
    if not code:
        # Виджет по метрике: его происхождение — формула, и её показывает
        # разбор «из чего складывается». Придумывать здесь второй ответ на тот
        # же вопрос не нужно.
        raise DashboardError("У этого виджета нет графы формы: смотрите разбор показателя")
    fields = [f for f in (field, cfg.get("value_field"), cfg.get("fact_field"),
                          cfg.get("plan_field")) if f]
    fields += [f for f in (cfg.get("value_fields") or []) if f]
    if not fields:
        raise DashboardError("У виджета не выбран показатель формы")
    value_field = fields[0]

    allowed = await allowed_rows_for_dataset(conn, org_id, user, code)
    name_row = await conn.fetchrow(
        "select cf.name from canonical_fields cf join dataset_releases r on r.object_id=cf.object_id "
        "where r.organization_id=$1 and r.code=$2 and cf.code=$3 limit 1", org_id, code, value_field)

    rels = await conn.fetch(
        "select r.id, r.reporting_period_start, r.status, r.created_at, r.auto_released, "
        "  u.full_name as author_name, u.login as author_login, "
        "  d.original_filename as document, d.id as document_id "
        "from dataset_releases r "
        "left join users u on u.id = r.created_by "
        "left join document_versions dv on dv.id = r.source_document_version_id "
        "left join documents d on d.id = dv.document_id "
        "where r.organization_id=$1 and r.code=$2 "
        "order by r.reporting_period_start nulls last, r.created_at",
        org_id, code)

    history: list[dict] = []
    for r in rels:
        params: list = [r["id"], value_field, row]
        acl = _row_acl_clause(params, allowed)
        vals = await conn.fetch(
            "select value_number from dataset_values "
            f"where dataset_release_id=$1 and canonical_field_code=$2 "
            f"  and value_number is not null and ($3::text is null or row_label=$3){acl}",
            *params)
        numbers = [float(v["value_number"]) for v in vals]
        if not numbers:
            continue
        # Свёртка — тем же правилом, что у карточки: доли усредняются, всё
        # остальное складывается. Иначе паспорт объяснял бы не ту цифру.
        value, how = aggregate_series(numbers, (name_row["name"] if name_row else value_field),
                                      cfg.get("unit"))
        history.append({
            "period": r["reporting_period_start"].isoformat() if r["reporting_period_start"] else None,
            "value": value,
            "aggregate": how,
            "rows_used": len(numbers),
            "document": r["document"],
            "document_id": str(r["document_id"]) if r["document_id"] else None,
            "released_at": r["created_at"].isoformat() if r["created_at"] else None,
            "released_by": r["author_name"] or r["author_login"],
            "auto_released": bool(r["auto_released"]),
            # Замещённый выпуск — тот, что заменили повторным выпуском за ту же
            # дату. Он остаётся в паспорте: это ответ на «почему цифра менялась».
            "superseded": r["status"] == "superseded",
        })

    # Прирост считаем только между ДЕЙСТВУЮЩИМИ выпусками: сравнивать с
    # замещённым значит показывать изменение, которого на дашборде не было.
    live = [h for h in history if not h["superseded"]]
    prev = None
    for h in live:
        if prev is not None and prev.get("value") is not None and h.get("value") is not None:
            h["delta"] = h["value"] - prev["value"]
            h["delta_pct"] = (h["delta"] / prev["value"] * 100) if prev["value"] else None
        prev = h

    return {
        "widget_name": w["name"],
        "dataset_code": code,
        "field": value_field,
        "field_name": name_row["name"] if name_row else value_field,
        "row": row,
        "fields": fields,
        "history": history,
    }
