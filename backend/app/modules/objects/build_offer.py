"""Есть ли у объекта дашборд — одно правило для плашки объекта и для журнала загрузки.

Правило жило внутри маршрута плашки «По объекту накоплено данных — собрать?»;
журнал «📥 Загрузки» (этап 4, 30.09.2026) спрашивает о том же, и вторая копия
однажды разошлась бы с первой — плашка звала бы собрать, а журнал молчал.
"""
from __future__ import annotations

from typing import Iterable, Set


async def objects_with_dashboards(conn, org_id, object_ids: Iterable[str]) -> Set[str]:
    """Какие из объектов уже смотрит хотя бы один не архивный дашборд.

    Двумя способами сразу: дашборд лежит в папке объекта (мастер ставит папку
    сам) ИЛИ его виджеты ссылаются на коды наборов объекта. Одного признака
    мало: дашборд могли собрать до автопривязки или перенести в другую папку.
    """
    ids = sorted({str(i) for i in object_ids if i})
    if not ids:
        return set()
    rows = await conn.fetch(
        "select distinct f.object_id from dashboards d join folders f on f.id = d.folder_id "
        "where d.organization_id = $1 and d.publication_status <> 'archived' "
        "  and f.object_id = any($2::uuid[]) "
        "union "
        "select distinct r.object_id from dataset_releases r "
        "join widgets w on w.organization_id = r.organization_id "
        "             and w.config->>'dataset_code' = r.code "
        "join dashboards d on d.id = w.dashboard_id and d.publication_status <> 'archived' "
        "where r.organization_id = $1 and r.object_id = any($2::uuid[]) "
        "  and r.status <> 'superseded'", org_id, ids)
    return {str(r["object_id"]) for r in rows}
