"""Сервис метрик: версии формул, зависимости, проверка циклов, статусы, предпросмотр.

Версии формул: draft → validated → approved (→ deprecated). Автор версии сам её
НЕ одобряет (конфликт интересов, как в модерации) — исключение сделано для
роли superadmin, которая может вести цикл в одиночку. Перед сохранением формула
разбирается в AST, извлекаются зависимости (датасеты/метрики), проверяется
отсутствие циклов. Предпросмотр вычисляет результат на реальных данных.
"""
from __future__ import annotations

import json
from typing import List, Optional

from ..audit import service as audit_svc
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
                        owner_id: Optional[str], owner_set: bool = False) -> dict:
    """Правка карточки показателя (admin/moderator): имя, краткое описание,
    расширенная информация (FR-5.9), владелец. Передавай только меняемые поля.

    `owner_set` отличает «владельца не трогаем» от «владельца СНИМАЕМ»: у
    остальных полей пустое значение означает «не менять», а у ответственного
    пустое — это осмысленный выбор (человек уволился, показатель передают), и
    без явного признака снять его было бы нечем.
    """
    m = await conn.fetchrow(
        "select id from metrics where id=$1::uuid and organization_id=$2", metric_id, org_id)
    if m is None:
        raise MetricError("Метрика не найдена")
    if owner_set and owner_id:
        # Владелец обязан быть сотрудником ЭТОЙ организации: чужой id в поле
        # ответственного означал бы жалобы, уходящие в никуда.
        ok = await conn.fetchval(
            "select 1 from users where id=$1::uuid and organization_id=$2", owner_id, org_id)
        if not ok:
            raise MetricError("Такого сотрудника нет в организации")
    row = await conn.fetchrow(
        "update metrics set name=coalesce($2,name), description=coalesce($3,description), "
        "info_text=coalesce($4,info_text), "
        "owner_id = case when $6 then $5::uuid else owner_id end "
        "where id=$1::uuid returning id, code, name, description, info_text, owner_id",
        metric_id, name, description, info_text, owner_id, owner_set)
    return dict(row)


async def _metric_usage(conn, org_id, metric_id: str, code: str) -> dict:
    """Кто опирается на показатель. Обе связи — ПО КОДУ, в jsonb и в разобранных
    формулах, поэтому внешних ключей на них нет и СУБД сама ничего не проверит."""
    widgets = await conn.fetch(
        "select w.name as widget_name, d.name as dashboard_name "
        "from widgets w "
        "join dashboards d on d.id = w.dashboard_id "
        "where w.organization_id = $1 and ("
        "  w.config->>'metric_code' = $2 or w.config->>'plan_metric' = $2 "
        "  or w.config->>'fact_metric' = $2)",
        org_id, code)

    # Формулы других показателей: ссылка живёт внутри разобранного AST,
    # достаём её тем же кодом, что и при проверке циклов.
    others = await conn.fetch(
        "select m.code, m.name, mv.formula_ast from metric_versions mv "
        "join metrics m on m.id = mv.metric_id "
        "where m.organization_id = $1 and m.id <> $2::uuid and mv.formula_ast is not null "
        "and mv.status <> 'deprecated'", org_id, metric_id)
    used_by_metrics = []
    for r in others:
        ast = r["formula_ast"]
        if isinstance(ast, str):
            ast = json.loads(ast)
        if code in extract_dependencies(ast)["metrics"]:
            label = f"{r['name']} ({r['code']})"
            if label not in used_by_metrics:
                used_by_metrics.append(label)

    return {
        "widgets": [f"«{r['widget_name']}» на дашборде «{r['dashboard_name']}»" for r in widgets],
        "metrics": used_by_metrics,
    }


async def delete_metric(conn, org_id, user_id, metric_id: str) -> dict:
    """Удаление показателя вместе с версиями формул (каскад в БД).

    Отказываем, пока показатель в работе: удалить его — значит сломать чужой
    виджет или чужую формулу, причём молча, ведь ссылка идёт по коду и внешнего
    ключа за ней нет. Причину называем поимённо, иначе непонятно, что чинить.
    """
    m = await conn.fetchrow(
        "select id, code, name from metrics where id=$1::uuid and organization_id=$2",
        metric_id, org_id)
    if m is None:
        raise MetricError("Метрика не найдена")

    usage = await _metric_usage(conn, org_id, metric_id, m["code"])
    if usage["widgets"] or usage["metrics"]:
        parts = []
        if usage["widgets"]:
            parts.append("используется виджетами: " + ", ".join(usage["widgets"][:5]))
        if usage["metrics"]:
            parts.append("на него ссылаются формулы показателей: " + ", ".join(usage["metrics"][:5]))
        raise MetricError("Удаление отменено — показатель в работе (" + "; ".join(parts) + ")")

    versions = await conn.fetch(
        "select version_no, status from metric_versions where metric_id=$1::uuid order by version_no",
        metric_id)
    await audit_svc.write_event(
        conn, org_id, user_id, "delete", "metric", metric_id,
        old_data={"code": m["code"], "name": m["name"],
                  "versions": [{"version_no": v["version_no"], "status": v["status"]} for v in versions]})
    # версии и metric_dependencies уходят каскадом (миграция 002)
    await conn.execute("delete from metrics where id=$1::uuid", metric_id)
    return {"deleted": True, "code": m["code"], "versions_deleted": len(versions)}


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
async def set_status(conn, org_id, user_id, version_id: str, target: str,
                     roles: Optional[set] = None) -> dict:
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
        # Конфликт интересов: свою версию одобряет только суперадмин (он же
        # владелец системы и может работать в одиночку). Факт самоодобрения
        # остаётся видимым: created_by и approved_by в строке совпадут.
        if ver["created_by"] == user_id and "superadmin" not in (roles or set()):
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
        # Первая строка по коду — самый свежий выпуск (порядок desc): из него
        # берём состав полей и строк. НО подписывать датасет одним файлом
        # нельзя: за кодом стоит ВЕСЬ ряд отчётов одной формы — пятнадцать
        # недель, а не «Приложение от 05.08». Человек, видя одно имя файла,
        # решает, что виджет посчитает по нему одному, и не понимает, откуда
        # берётся динамика. Поэтому собираем список всех файлов кода.
        grp = by_code.setdefault(code, {"code": code, "name": r["name"], "object": r["object_name"],
                                        "object_id": r["object_id"], "latest_id": r["id"], "dates": [],
                                        "folder": r["folder"], "document": r["document"],
                                        "documents": [], "releases": 0})
        grp["releases"] += 1
        if r["document"] and r["document"] not in grp["documents"]:
            grp["documents"].append(r["document"])
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
            "folder": grp["folder"],
            # `document` — файл ПОСЛЕДНЕГО отчёта (по нему считаются карточки);
            # `documents`/`releases` показывают, что за кодом стоит целый ряд.
            "document": grp["document"], "documents": grp["documents"],
            "releases": grp["releases"], "dates": grp["dates"],
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


async def current_values(conn, org_id, codes: Optional[List[str]] = None, limit: int = 60) -> dict:
    """Что показатели считают ПРЯМО СЕЙЧАС — по лучшей версии формулы.

    В списке показателей были только имя и статус: понять, что метрика даёт на
    сегодняшних данных, можно было лишь открыв её и нажав предпросмотр. При
    полутора десятках показателей это означало полтора десятка заходов, а
    сломанная формула вообще ничем себя не выдавала — она выглядела как
    обычная строка списка.

    Берём ту же версию, что берёт виджет (одобренная → проверенная →
    черновик), — иначе список показывал бы одно, а дашборд считал другое.
    Ошибку не прячем: не посчиталось — так и говорим, это и есть самый ценный
    ответ для модератора.
    """
    where = "m.organization_id=$1"
    params: list = [org_id]
    if codes:
        params.append(list(codes))
        where += f" and m.code = any(${len(params)}::text[])"
    rows = await conn.fetch(
        "select m.code, m.name, "
        "  (select mv.id from metric_versions mv where mv.metric_id=m.id "
        "     order by case mv.status when 'approved' then 0 when 'validated' then 1 "
        "                             when 'draft' then 2 else 3 end, mv.version_no desc limit 1) as version_id, "
        "  (select mv.status from metric_versions mv where mv.metric_id=m.id "
        "     order by case mv.status when 'approved' then 0 when 'validated' then 1 "
        "                             when 'draft' then 2 else 3 end, mv.version_no desc limit 1) as status "
        f"from metrics m where {where} order by m.name limit {int(limit)}", *params)

    out = []
    for r in rows:
        item = {"code": r["code"], "name": r["name"], "status": r["status"],
                "value": None, "unit": None, "error": None}
        if r["version_id"] is None:
            item["error"] = "у показателя нет ни одной версии формулы"
        else:
            try:
                got = await evaluate_version(conn, org_id, str(r["version_id"]))
                item["value"], item["unit"] = got["value"], got["unit"]
            except MetricError as e:
                item["error"] = str(e)
            except Exception as e:  # noqa: BLE001 — одна кривая формула не должна ронять весь список
                item["error"] = f"ошибка расчёта: {e}"
        out.append(item)
    return {"items": out}


async def bulk_set_status(conn, org_id, user_id, version_ids: List[str], target: str,
                          roles: Optional[set] = None) -> dict:
    """Проверить или одобрить несколько версий разом.

    Заводя показатели пачкой (мастер и предложения по данным создают их
    десятками), человек упирался в десяток одинаковых нажатий. Массовая
    операция — та же самая `set_status` в цикле: **правила не ослаблены**,
    и это главное. Свою версию по-прежнему нельзя одобрить (кроме
    суперадминистратора), черновик нельзя одобрить в обход проверки.

    Отказ по одной версии не отменяет остальные: возвращаем поимённо, что
    прошло и что нет, — иначе одна чужая метрика в списке блокировала бы
    работу со всеми, а человек не понял бы, какая именно.
    """
    done, failed = [], []
    for vid in version_ids:
        try:
            await set_status(conn, org_id, user_id, vid, target, roles)
            done.append(vid)
        except MetricError as e:
            failed.append({"version_id": vid, "error": str(e)})
    return {"target": target, "done": done, "failed": failed,
            "ok": len(done), "skipped": len(failed)}


async def pending_versions(conn, org_id, target: str) -> list:
    """Версии, к которым применима массовая операция: что именно будет затронуто.

    Человек должен видеть список ДО нажатия: массовое одобрение — это решение
    по каждому показателю, а не «нажать и забыть».
    """
    status = "draft" if target == "validated" else "validated"
    rows = await conn.fetch(
        "select mv.id as version_id, mv.version_no, mv.created_by, m.code, m.name "
        "from metric_versions mv join metrics m on m.id = mv.metric_id "
        "where m.organization_id=$1 and mv.status=$2 order by m.name",
        org_id, status)
    return [
        {"version_id": str(r["version_id"]), "version_no": r["version_no"],
         "code": r["code"], "name": r["name"], "created_by": str(r["created_by"])}
        for r in rows
    ]
