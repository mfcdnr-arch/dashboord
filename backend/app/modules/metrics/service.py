"""Сервис метрик: версии формул, зависимости, проверка циклов, статусы, предпросмотр.

Версии формул: draft → validated → approved (→ deprecated). Автор версии сам её
НЕ одобряет (конфликт интересов, как в модерации). Перед сохранением формула
разбирается в AST, извлекаются зависимости (датасеты/метрики), проверяется
отсутствие циклов. Предпросмотр вычисляет результат на реальных данных.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

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
