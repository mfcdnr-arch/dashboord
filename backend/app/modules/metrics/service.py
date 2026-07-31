"""Сервис метрик: версии формул, зависимости, проверка циклов, статусы, предпросмотр.

Версии формул: draft → validated → approved (→ deprecated). Автор версии сам её
НЕ одобряет (конфликт интересов, как в модерации). Перед сохранением формула
разбирается в AST, извлекаются зависимости (датасеты/метрики), проверяется
отсутствие циклов. Предпросмотр вычисляет результат на реальных данных.
"""
from __future__ import annotations

import json
from typing import List, Optional

from . import resolver
from .cycles import CycleError, validate_and_topo_sort
from .parser import FormulaError, extract_dependencies, parse


class MetricError(Exception):
    """Ошибка бизнес-логики метрик (в роутере → 400/409)."""


# --------------------------------------------------------------------------- #
# Проверка циклов на уровне кодов метрик
# --------------------------------------------------------------------------- #
async def _check_no_cycle(conn, org_id, metric_code: str, new_metric_deps: List[str]) -> None:
    """Строит граф зависимостей метрик (по последним версиям) c учётом новой формулы."""
    rows = await conn.fetch(
        "select m.code, mv.formula_ast from metrics m "
        "join lateral (select formula_ast from metric_versions v "
        "  where v.metric_id=m.id order by version_no desc limit 1) mv on true "
        "where m.organization_id=$1",
        org_id,
    )
    nodes = {metric_code}
    edges: List[tuple] = []
    for r in rows:
        code = r["code"]
        nodes.add(code)
        if code == metric_code:
            continue  # заменяем на новую версию ниже
        ast = r["formula_ast"]
        if isinstance(ast, str):
            ast = json.loads(ast)
        for dep in extract_dependencies(ast)["metrics"]:
            nodes.add(dep)
            edges.append((code, dep))
    for dep in new_metric_deps:
        nodes.add(dep)
        edges.append((metric_code, dep))
    try:
        validate_and_topo_sort(nodes, edges)
    except CycleError as e:
        raise MetricError(str(e))


# --------------------------------------------------------------------------- #
# CRUD метрик
# --------------------------------------------------------------------------- #
async def create_metric(conn, org_id, user_id, code: str, name: str,
                        description: Optional[str], owner_id: Optional[str]) -> dict:
    exists = await conn.fetchval(
        "select 1 from metrics where organization_id=$1 and code=$2", org_id, code
    )
    if exists:
        raise MetricError("Метрика с таким кодом уже существует")
    row = await conn.fetchrow(
        "insert into metrics(organization_id, code, name, description, owner_id, created_by) "
        "values($1,$2,$3,$4,$5::uuid,$6) returning id, code, name, description, created_at",
        org_id, code, name, description, owner_id, user_id,
    )
    return dict(row)


async def update_metric(conn, org_id, metric_id: str, name: Optional[str],
                        description: Optional[str], info_text: Optional[str],
                        owner_id: Optional[str]) -> dict:
    """Правка карточки показателя (admin/moderator): имя, краткое описание,
    расширенная информация (FR-5.9), владелец. Передавай только меняемые поля."""
    m = await conn.fetchrow(
        "select id from metrics where id=$1::uuid and organization_id=$2", metric_id, org_id)
    if m is None:
        raise MetricError("Метрика не найдена")
    row = await conn.fetchrow(
        "update metrics set name=coalesce($2,name), description=coalesce($3,description), "
        "info_text=coalesce($4,info_text), owner_id=coalesce($5::uuid,owner_id) "
        "where id=$1::uuid returning id, code, name, description, info_text",
        metric_id, name, description, info_text, owner_id)
    return dict(row)


async def create_version(conn, org_id, user_id, metric_id: str, formula_expression: str,
                         unit: Optional[str], grain: Optional[str],
                         calculation_type: str) -> dict:
    metric = await conn.fetchrow(
        "select id, code from metrics where id=$1::uuid and organization_id=$2", metric_id, org_id
    )
    if metric is None:
        raise MetricError("Метрика не найдена")

    try:
        ast = parse(formula_expression)
    except FormulaError as e:
        raise MetricError(f"Ошибка формулы: {e}")
    deps = extract_dependencies(ast)

    await _check_no_cycle(conn, org_id, metric["code"], deps["metrics"])

    next_no = await conn.fetchval(
        "select coalesce(max(version_no),0)+1 from metric_versions where metric_id=$1::uuid", metric_id
    )
    ver = await conn.fetchrow(
        "insert into metric_versions(metric_id, version_no, status, formula_expression, "
        "formula_ast, unit, grain, calculation_type, created_by) "
        "values($1::uuid,$2,'draft',$3,$4::jsonb,$5,$6,$7,$8) returning id, version_no, status",
        metric_id, next_no, formula_expression,
        json.dumps(ast, ensure_ascii=False), unit, grain, calculation_type, user_id,
    )
    version_id = ver["id"]

    # зависимости: датасеты (по активному выпуску) и метрики (по последней версии)
    for ds_code in deps["datasets"]:
        rel = await resolver._active_release(conn, org_id, ds_code)
        if rel is not None:
            await conn.execute(
                "insert into metric_dependencies(metric_version_id, depends_on_dataset_release_id) "
                "values($1,$2)", version_id, rel,
            )
    for m_code in deps["metrics"]:
        dep_ver = await conn.fetchval(
            "select mv.id from metrics m join metric_versions mv on mv.metric_id=m.id "
            "where m.organization_id=$1 and m.code=$2 order by mv.version_no desc limit 1",
            org_id, m_code,
        )
        if dep_ver is not None:
            await conn.execute(
                "insert into metric_dependencies(metric_version_id, depends_on_metric_version_id) "
                "values($1,$2)", version_id, dep_ver,
            )

    return {"version_id": str(version_id), "version_no": ver["version_no"], "status": ver["status"],
            "dependencies": deps}


# --------------------------------------------------------------------------- #
# Смена статуса версии
# --------------------------------------------------------------------------- #
async def set_status(conn, org_id, user_id, version_id: str, target: str) -> dict:
    ver = await conn.fetchrow(
        "select mv.id, mv.metric_id, mv.status, mv.created_by from metric_versions mv "
        "join metrics m on m.id=mv.metric_id "
        "where mv.id=$1::uuid and m.organization_id=$2", version_id, org_id
    )
    if ver is None:
        raise MetricError("Версия метрики не найдена")

    if target == "validated":
        if ver["status"] != "draft":
            raise MetricError("Проверить можно только черновик")
        await conn.execute("update metric_versions set status='validated' where id=$1::uuid", version_id)
    elif target == "approved":
        if ver["status"] != "validated":
            raise MetricError("Одобрить можно только проверенную версию")
        if ver["created_by"] == user_id:
            raise MetricError("Нельзя одобрять собственную версию (конфликт интересов)")
        # снять одобрение с прочих версий этой метрики
        await conn.execute(
            "update metric_versions set status='deprecated' "
            "where metric_id=$1 and status='approved'", ver["metric_id"]
        )
        await conn.execute(
            "update metric_versions set status='approved', approved_by=$2, approved_at=now() "
            "where id=$1::uuid", version_id, user_id
        )
    else:
        raise MetricError(f"Недопустимый переход статуса: {target}")
    return {"version_id": version_id, "status": target}


# --------------------------------------------------------------------------- #
# Предпросмотр и вычисление
# --------------------------------------------------------------------------- #
async def preview(conn, org_id, formula_expression: str) -> dict:
    try:
        ast = parse(formula_expression)
    except FormulaError as e:
        raise MetricError(f"Ошибка формулы: {e}")
    deps = extract_dependencies(ast)
    try:
        value = await resolver.evaluate_ast(conn, org_id, ast)
    except FormulaError as e:
        raise MetricError(str(e))
    return {"value": value, "dependencies": deps, "ast": ast}


async def list_data_sources(conn, org_id) -> dict:
    """Справочник для визуального конструктора: датасеты (поля/строки/даты) + метрики."""
    releases = await conn.fetch(
        "select r.id, r.code, r.name, r.object_id, r.reporting_period_start, o.name as object_name, "
        "doc.original_filename as document, f.name as folder "
        "from dataset_releases r "
        "left join objects o on o.id=r.object_id "
        "left join document_versions dv on dv.id = r.source_document_version_id "
        "left join documents doc on doc.id = dv.document_id "
        "left join folders f on f.id = doc.folder_id "
        "where r.organization_id=$1 and r.status <> 'superseded' "
        "order by r.code, r.reporting_period_start desc nulls last, r.created_at desc",
        org_id,
    )
    by_code: dict = {}
    for r in releases:
        code = r["code"]
        # первая строка по коду — самый свежий выпуск (порядок desc): берём его источник
        grp = by_code.setdefault(code, {"code": code, "name": r["name"], "object": r["object_name"],
                                        "object_id": r["object_id"], "latest_id": r["id"], "dates": [],
                                        "folder": r["folder"], "document": r["document"]})
        if r["reporting_period_start"] is not None:
            d = r["reporting_period_start"].isoformat()
            if d not in grp["dates"]:
                grp["dates"].append(d)

    datasets = []
    for grp in by_code.values():
        fields = await conn.fetch(
            "select drf.canonical_field_code as code, "
            "coalesce(cf.name, drf.canonical_field_code) as name, "
            "coalesce(cf.data_type,'text') as data_type, coalesce(cf.is_row_label,false) as is_row_label "
            "from dataset_release_fields drf "
            "left join canonical_fields cf on cf.object_id=$2 and cf.code=drf.canonical_field_code "
            "where drf.dataset_release_id=$1 order by drf.canonical_field_code",
            grp["latest_id"], grp["object_id"],
        )
        rows = await conn.fetch(
            "select distinct row_label from dataset_values "
            "where dataset_release_id=$1 and row_label is not null order by row_label limit 300",
            grp["latest_id"],
        )
        datasets.append({
            "code": grp["code"], "name": grp["name"], "object": grp["object"],
            "folder": grp["folder"], "document": grp["document"], "dates": grp["dates"],
            "fields": [dict(f) for f in fields],
            "rows": [r["row_label"] for r in rows],
        })

    # метрики + подсказки: единица и формула лучшей версии (approved→validated→draft)
    metrics = await conn.fetch(
        "select m.code, m.name, "
        "(select mv.unit from metric_versions mv where mv.metric_id=m.id "
        " order by (case mv.status when 'approved' then 0 when 'validated' then 1 else 2 end), "
        " mv.version_no desc limit 1) as unit, "
        "(select mv.formula_expression from metric_versions mv where mv.metric_id=m.id "
        " order by (case mv.status when 'approved' then 0 when 'validated' then 1 else 2 end), "
        " mv.version_no desc limit 1) as formula "
        "from metrics m where m.organization_id=$1 order by m.name", org_id
    )
    return {"datasets": datasets, "metrics": [dict(m) for m in metrics]}


async def evaluate_version(conn, org_id, version_id: str) -> dict:
    row = await conn.fetchrow(
        "select mv.formula_ast, mv.unit from metric_versions mv "
        "join metrics m on m.id=mv.metric_id "
        "where mv.id=$1::uuid and m.organization_id=$2", version_id, org_id
    )
    if row is None:
        raise MetricError("Версия метрики не найдена")
    ast = row["formula_ast"]
    if isinstance(ast, str):
        ast = json.loads(ast)
    try:
        value = await resolver.evaluate_ast(conn, org_id, ast)
    except FormulaError as e:
        raise MetricError(str(e))
    return {"value": value, "unit": row["unit"]}
