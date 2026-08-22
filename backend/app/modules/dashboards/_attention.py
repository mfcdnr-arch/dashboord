"""«На что посмотреть» — замечания к данным прямо на дашборде.

Проверки качества (`ingestion/quality`) существуют с 15.08, но их видит ТОЛЬКО
модератор и только в момент выпуска: нажал «Выпустить» — прочитал — забыл.
Руководитель, который открывает дашборд неделю спустя, видит цифры и ничего не
знает о том, что строка «Донецкая Народная Республика» совпала с прошлым
отчётом посимвольно, то есть данные могли не обновить.

Здесь те же правила применяются к УЖЕ ВЫПУЩЕННЫМ данным: последний активный
выпуск сравнивается с предыдущим тем же `compare_with_previous`. Своих правил
нет намеренно — иначе дашборд и модератор говорили бы разное об одних данных.

Что сравнивается, определяет сама страница: датасеты берутся из её виджетов.
Row-level RLS соблюдается — замечание не должно называть строку, которую этому
человеку видеть не положено.
"""
from __future__ import annotations

from typing import Dict, List

from ..ingestion.quality import compare_with_previous, previous_release_values
from ._rowrls import allowed_rows_for_dataset

# Больше трёх форм на странице — редкость; ограничение защищает от страницы,
# собранной по десятку датасетов, где блок превратился бы в простыню.
MAX_DATASETS = 3


async def _release_values(conn, rel_id) -> Dict[tuple, float]:
    rows = await conn.fetch(
        "select row_label, canonical_field_code, value_number from dataset_values "
        "where dataset_release_id=$1 and value_number is not null", rel_id)
    return {(r["row_label"] or "", r["canonical_field_code"]): float(r["value_number"]) for r in rows}


def _filter_allowed(values: Dict[tuple, float], allowed) -> Dict[tuple, float]:
    """Строки, недоступные пользователю, выбрасываем ДО проверок: иначе
    замечание процитировало бы скрытую строку по имени и с числом."""
    if allowed is None:
        return values
    return {k: v for k, v in values.items() if k[0] in allowed}


async def page_attention(conn, org_id, page_id: str, user: dict) -> dict:
    """Замечания к данным, на которых построена страница."""
    from . import service  # ленивый импорт: service тянет этот модуль

    wl = await service.list_page_widgets(conn, org_id, page_id, user)
    hits: Dict[str, int] = {}
    for w in wl["widgets"]:
        code = (w.get("config") or {}).get("dataset_code")
        if code:
            hits[code] = hits.get(code, 0) + 1
    codes = sorted(hits, key=lambda c: (-hits[c], c))[:MAX_DATASETS]

    items: List[dict] = []
    for code in codes:
        rel = await conn.fetchrow(
            "select r.id, r.name, r.reporting_period_start, r.object_id "
            "from dataset_releases r where r.organization_id=$1 and r.code=$2 and r.status<>'superseded' "
            "order by r.reporting_period_start desc nulls last, r.created_at desc limit 1", org_id, code)
        if rel is None:
            continue
        allowed = await allowed_rows_for_dataset(conn, org_id, user, code) if user is not None else None
        current = _filter_allowed(await _release_values(conn, rel["id"]), allowed)
        previous, prev_period = await previous_release_values(
            conn, org_id, code, rel["reporting_period_start"])
        previous = _filter_allowed(previous, allowed)
        if not current or not previous:
            # Первый выпуск формы: сравнивать не с чем — это не замечание.
            continue
        names = {r["code"]: r["name"] for r in await conn.fetch(
            "select code, name from canonical_fields where object_id=$1", rel["object_id"])}
        warnings = compare_with_previous(current, previous, names, prev_period)
        if warnings:
            period = rel["reporting_period_start"]
            items.append({
                "dataset_code": code,
                "dataset_name": rel["name"],
                "period": period.isoformat() if period else None,
                "previous_period": prev_period,
                "warnings": warnings,
            })
    return {"items": items, "datasets_checked": len(codes)}
