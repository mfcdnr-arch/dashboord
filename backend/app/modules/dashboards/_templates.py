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


# Ключи config, ссылающиеся на коды датасетов, метрик и ПОЛЕЙ. Поля важны не
# меньше датасета: у другого объекта коды полей свои (они выводятся из
# заголовков его формы), и виджет, перенесённый как есть, показал бы ошибку.
_DATASET_KEYS = ("dataset_code",)
_METRIC_KEYS = ("metric_code", "plan_metric", "fact_metric")
_FIELD_KEYS = ("value_field", "plan_field", "fact_field", "label_field")
_FIELD_LIST_KEYS = ("value_fields",)


def _template_codes(spec: dict) -> dict:
    """Какие коды датасетов/метрик/полей использует шаблон (для перепривязки)."""
    datasets, metrics, fields = set(), set(), set()
    for page in spec.get("pages", []):
        for w in page.get("widgets", []):
            cfg = w.get("config", {}) or {}
            for k in _DATASET_KEYS:
                if cfg.get(k):
                    datasets.add(cfg[k])
            for k in _METRIC_KEYS:
                if cfg.get(k):
                    metrics.add(cfg[k])
            for k in _FIELD_KEYS:
                if cfg.get(k):
                    fields.add(cfg[k])
            for k in _FIELD_LIST_KEYS:
                for f in cfg.get(k) or []:
                    fields.add(f)
            # «Сравнение источников»: у каждой серии свой датасет и своё поле.
            for srs in cfg.get("series") or []:
                if isinstance(srs, dict):
                    if srs.get("dataset_code"):
                        datasets.add(srs["dataset_code"])
                    if srs.get("value_field"):
                        fields.add(srs["value_field"])
    return {"datasets": sorted(datasets), "metrics": sorted(metrics), "fields": sorted(fields)}


def _remap_config(cfg: dict, dmap: dict, mmap: dict, fmap: Optional[dict] = None) -> dict:
    """Применяет карты перепривязки (старый код → новый) к config виджета."""
    fmap = fmap or {}
    out = dict(cfg or {})
    for k in _DATASET_KEYS:
        if out.get(k) and out[k] in dmap:
            out[k] = dmap[out[k]]
    for k in _METRIC_KEYS:
        if out.get(k) and out[k] in mmap:
            out[k] = mmap[out[k]]
    for k in _FIELD_KEYS:
        if out.get(k) and out[k] in fmap:
            out[k] = fmap[out[k]]
    for k in _FIELD_LIST_KEYS:
        if out.get(k):
            out[k] = [fmap.get(f, f) for f in out[k]]
    if out.get("series"):
        out["series"] = [
            {**srs,
             **({"dataset_code": dmap[srs["dataset_code"]]}
                if isinstance(srs, dict) and srs.get("dataset_code") in dmap else {}),
             **({"value_field": fmap[srs["value_field"]]}
                if isinstance(srs, dict) and srs.get("value_field") in fmap else {})}
            if isinstance(srs, dict) else srs
            for srs in out["series"]
        ]
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
                               dataset_map: Optional[dict] = None, metric_map: Optional[dict] = None,
                               field_map: Optional[dict] = None, folder_id: Optional[str] = None) -> dict:
    spec = await conn.fetchval(
        "select spec from dashboard_templates where id=$1::uuid and organization_id=$2", template_id, org_id)
    if spec is None:
        raise DashboardError("Шаблон не найден")
    if isinstance(spec, str):
        spec = json.loads(spec)
    from . import service as svc  # ленивый импорт: избегаем цикла модулей
    dmap, mmap, fmap = dataset_map or {}, metric_map or {}, field_map or {}
    dash = await svc.create_dashboard(conn, org_id, user_id, name, "Создан из шаблона", folder_id)
    did = str(dash["id"])
    for page in spec.get("pages", []):
        p = await svc.create_page(conn, org_id, user_id, did, page["name"], page.get("description"))
        for w in page.get("widgets", []):
            cfg = _remap_config(w.get("config", {}), dmap, mmap, fmap)
            await svc.create_widget(conn, org_id, user_id, str(p["id"]), w["name"], w["widget_type"], cfg,
                                {"position_x": w.get("position_x", 0), "position_y": w.get("position_y", 0),
                                 "width": w.get("width", 4), "height": w.get("height", 4)})
    return {"dashboard_id": did}


async def _field_names(conn, org_id, dataset_code: str) -> dict:
    """Коды полей датасета → человеческие имена (из справочника объекта)."""
    rows = await conn.fetch(
        "select distinct drf.canonical_field_code as code, "
        "  coalesce(cf.name, drf.canonical_field_code) as name "
        "from dataset_releases r "
        "join dataset_release_fields drf on drf.dataset_release_id = r.id "
        "left join canonical_fields cf on cf.object_id = r.object_id "
        "  and cf.code = drf.canonical_field_code "
        "where r.organization_id=$1 and r.code=$2 and r.status <> 'superseded'",
        org_id, dataset_code)
    return {r["code"]: r["name"] for r in rows}


def _norm(name: str) -> str:
    """Ключ сопоставления показателей — как в разметке: регистр и пробелы."""
    return " ".join((name or "").replace("*", " ").split()).lower()


async def suggest_binding(conn, org_id, template_id: str, object_id: str) -> dict:
    """Как лечь шаблону на ДРУГОЙ объект: сопоставление датасетов и показателей.

    Ради этого всё и делается: у второго объекта своя форма, и коды полей у
    него свои — они выводятся из его заголовков. Перенесённый как есть виджет
    показал бы ошибку «нет данных», причём на каждом виджете по отдельности.

    Сопоставляем по ИМЕНАМ показателей: имя — единственное, что устойчиво
    повторяется в одинаковых формах разных подразделений. Что не нашлось —
    возвращаем честным списком, а не подставляем «похожее»: неверно
    сопоставленный показатель хуже отсутствующего, потому что он выглядит
    рабочим.
    """
    from ._suggest import collect_object_datasets

    spec = await conn.fetchval(
        "select spec from dashboard_templates where id=$1::uuid and organization_id=$2",
        template_id, org_id)
    if spec is None:
        raise DashboardError("Шаблон не найден")
    if isinstance(spec, str):
        spec = json.loads(spec)
    codes = _template_codes(spec)

    targets = await collect_object_datasets(conn, org_id, object_id)
    if not targets:
        raise DashboardError("У объекта нет выпущенных данных — переносить шаблон не на что")
    # Целевой набор один: объект = одна форма. Если их несколько, берём самый
    # свежий (он же первый в collect_object_datasets).
    target = targets[0]
    target_by_name = {_norm(f["name"]): f["code"] for f in target["fields"]}

    dataset_map = {c: target["code"] for c in codes["datasets"]}
    field_map, matched, missing = {}, [], []
    for src_ds in codes["datasets"]:
        names = await _field_names(conn, org_id, src_ds)
        for code in codes["fields"]:
            if code in field_map:
                continue
            src_name = names.get(code)
            if src_name is None:
                continue
            tgt = target_by_name.get(_norm(src_name))
            if tgt:
                field_map[code] = tgt
                matched.append({"from": code, "from_name": src_name, "to": tgt})
            else:
                missing.append({"from": code, "from_name": src_name})

    # Показатель, которого нет в справочнике исходного объекта, тоже не перенести.
    unknown = [c for c in codes["fields"] if c not in field_map
               and not any(m["from"] == c for m in missing)]
    missing += [{"from": c, "from_name": c} for c in unknown]

    return {
        "target": {"dataset_code": target["code"], "dataset_name": target["name"],
                   "fields": target["fields"]},
        "dataset_map": dataset_map,
        "field_map": field_map,
        "matched": matched,
        "missing": missing,
        "metrics": codes["metrics"],
    }
