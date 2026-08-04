"""Шаблоны дашбордов: сохранение, список, перепривязка кодов, создание копии.

Вынесено из service.py; функции реэкспортируются оттуда — внешние вызовы
(`service.save_as_template` и т.п.) продолжают работать без изменений.
"""
from __future__ import annotations

import json
from typing import Optional

from ._base import DashboardError


# --------------------------------------------------------------------------- #
# Шаблоны дашбордов
# --------------------------------------------------------------------------- #
async def save_as_template(conn, org_id, user_id, dashboard_id: str, name: str, description=None) -> dict:
    from . import service as svc  # ленивый импорт: избегаем цикла модулей
    if not await svc._owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    if await conn.fetchval("select 1 from dashboard_templates where organization_id=$1 and name=$2", org_id, name):
        raise DashboardError("Шаблон с таким именем уже есть")
    spec = await svc._snapshot(conn, dashboard_id)
    row = await conn.fetchrow(
        "insert into dashboard_templates(organization_id, name, description, spec, created_by) "
        "values($1,$2,$3,$4::jsonb,$5) returning id, name",
        org_id, name, description, json.dumps(spec, ensure_ascii=False), user_id)
    return {"id": str(row["id"]), "name": row["name"]}


async def list_templates(conn, org_id) -> list:
    rows = await conn.fetch(
        "select id, name, description, created_at from dashboard_templates "
        "where organization_id=$1 order by name", org_id)
    return [dict(r) for r in rows]


# Ключи config, ссылающиеся на коды датасетов и метрик (для перепривязки шаблона).
_DATASET_KEYS = ("dataset_code",)
_METRIC_KEYS = ("metric_code", "plan_metric", "fact_metric")


def _template_codes(spec: dict) -> dict:
    """Какие коды датасетов/метрик использует шаблон (для перепривязки при клоне)."""
    datasets, metrics = set(), set()
    for page in spec.get("pages", []):
        for w in page.get("widgets", []):
            cfg = w.get("config", {}) or {}
            for k in _DATASET_KEYS:
                if cfg.get(k):
                    datasets.add(cfg[k])
            for k in _METRIC_KEYS:
                if cfg.get(k):
                    metrics.add(cfg[k])
    return {"datasets": sorted(datasets), "metrics": sorted(metrics)}


def _remap_config(cfg: dict, dmap: dict, mmap: dict) -> dict:
    """Применяет карты перепривязки (старый код → новый) к config виджета."""
    out = dict(cfg or {})
    for k in _DATASET_KEYS:
        if out.get(k) and out[k] in dmap:
            out[k] = dmap[out[k]]
    for k in _METRIC_KEYS:
        if out.get(k) and out[k] in mmap:
            out[k] = mmap[out[k]]
    return out


async def template_bindings(conn, org_id, template_id: str) -> dict:
    """Коды датасетов/метрик, которые использует шаблон — для UI перепривязки."""
    spec = await conn.fetchval(
        "select spec from dashboard_templates where id=$1::uuid and organization_id=$2", template_id, org_id)
    if spec is None:
        raise DashboardError("Шаблон не найден")
    if isinstance(spec, str):
        spec = json.loads(spec)
    return _template_codes(spec)


async def create_from_template(conn, org_id, user_id, template_id: str, name: str,
                               dataset_map: Optional[dict] = None, metric_map: Optional[dict] = None) -> dict:
    spec = await conn.fetchval(
        "select spec from dashboard_templates where id=$1::uuid and organization_id=$2", template_id, org_id)
    if spec is None:
        raise DashboardError("Шаблон не найден")
    if isinstance(spec, str):
        spec = json.loads(spec)
    from . import service as svc  # ленивый импорт: избегаем цикла модулей
    dmap, mmap = dataset_map or {}, metric_map or {}
    dash = await svc.create_dashboard(conn, org_id, user_id, name, "Создан из шаблона", None)
    did = str(dash["id"])
    for page in spec.get("pages", []):
        p = await svc.create_page(conn, org_id, user_id, did, page["name"], page.get("description"))
        for w in page.get("widgets", []):
            cfg = _remap_config(w.get("config", {}), dmap, mmap)
            await svc.create_widget(conn, org_id, user_id, str(p["id"]), w["name"], w["widget_type"], cfg,
                                {"position_x": w.get("position_x", 0), "position_y": w.get("position_y", 0),
                                 "width": w.get("width", 4), "height": w.get("height", 4)})
    return {"dashboard_id": did}
