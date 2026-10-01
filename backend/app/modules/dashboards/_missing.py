"""Подсказка «💡 новые графы не показаны» на дашборде (этап 5, 01.10.2026).

Форма прирастает графами, дашборд остаётся прежним, и узнать об этом можно было
только сверив их вручную. Подсказка была и раньше, но отвечала на другой вопрос
— «какой графы с числами не называет ни один виджет» — и на дашборде РЦО
насчитывала 359 таких из 384: туда попадали услуги, давно ушедшие из формы,
графы, показанные таблицей, и всё, что планировщик сознательно не вынес в
карточки при сборке. Подсказка, которая всегда говорит «359», не говорит ничего.

Теперь она отвечает на вопрос «что появилось в форме с тех пор, как дашборд
собрали»:
  • кандидаты — графы с числами в ПОСЛЕДНЕМ выпуске формы (не вся история);
  • минус графы, которые виджеты называют прямо (`_coverage.named_fields`);
  • минус «база дашборда» — графы, объявленные в выпусках, созданных ДО первого
    виджета на этой форме: их видел тот, кто собирал дашборд, и выбрал
    сознательно. Дата создания виджета, а не выпуска: перевыпуск 22.09
    пересоздал все выпуски РЦО, и отсчёт по выпускам объявил бы новыми все
    384 графы; прежние (снятые) выпуски при этом остаются и базу держат;
  • минус отмеченные человеком «больше не предлагать» (dashboards.fields_reviewed);
  • минус безымянные «Столбец N» (код сдвигается при каждом росте формы).
Графы, которые виджет показывает НЕЯВНО (таблица всей формы, рейтинг по мере),
не прячутся, а называются: «уже видна в «…»».
"""
from __future__ import annotations

import json
from typing import Dict, List

from ..ingestion.hierarchy import pick_separator
from ..ingestion.new_fields import is_unnamed
from . import _coverage, _levels
from ._aggregate import is_total_column
from ._base import DashboardError


def _cfg(raw) -> dict:
    return json.loads(raw) if isinstance(raw, str) else (raw or {})


async def missing_dashboard_fields(conn, org_id, dashboard_id: str) -> dict:
    """Новые с момента сборки графы форм дашборда, которых нет ни в одном виджете."""
    d = await conn.fetchrow(
        "select fields_reviewed from dashboards where id=$1::uuid and organization_id=$2",
        dashboard_id, org_id)
    if d is None:
        return {"fields": [], "count": 0}
    reviewed_all = _cfg(d["fields_reviewed"])
    widgets = await conn.fetch(
        "select name, widget_type, config, created_at from widgets where dashboard_id=$1::uuid",
        dashboard_id)

    named: set = set()
    first_widget_at: Dict[str, object] = {}
    whole: Dict[str, List[str]] = {}
    measures: Dict[str, List[tuple]] = {}
    for w in widgets:
        cfg = _cfg(w["config"])
        named.update(_coverage.named_fields(cfg))
        for code in _coverage.dataset_codes(cfg):
            at = first_widget_at.get(code)
            if at is None or w["created_at"] < at:
                first_widget_at[code] = w["created_at"]
        own = cfg.get("dataset_code")
        if own and _coverage.reads_whole_form(w["widget_type"], cfg):
            whole.setdefault(own, []).append(w["name"])
        m = _coverage.measure_of_cfg(cfg)
        if own and m:
            measures.setdefault(own, []).append((m, w["name"]))

    out: List[dict] = []
    for code, since in sorted(first_widget_at.items()):
        latest = await conn.fetchrow(
            "select id, object_id from dataset_releases "
            "where organization_id=$1 and code=$2 and status <> 'superseded' "
            "order by reporting_period_start desc nulls last, created_at desc limit 1",
            org_id, code)
        if latest is None:
            continue
        numeric = {r["c"] for r in await conn.fetch(
            "select distinct canonical_field_code as c from dataset_values "
            "where dataset_release_id=$1 and value_number is not null", latest["id"])}
        # База: графы выпусков, созданных до первого виджета этой формы. Если
        # дашборд собран раньше любого выпуска (шаблон, ручная сборка до
        # данных), базой служит первый выпуск — иначе «новой» оказалась бы
        # вся форма.
        #
        # Графы базы — по объявлениям выпуска, а у выпусков без объявлений (их
        # писали в обход штатного пути до 23.09) — по значениям. Значения
        # читаем ТОЛЬКО у таких выпусков: у РЦО в базе полсотни отчётов по
        # двадцать тысяч значений, и чтение всех сделало бы подсказку тяжёлой.
        base_rows = await conn.fetch(
            "with base0 as (select id from dataset_releases where organization_id=$1 and code=$2 "
            "                 and created_at <= $3), "
            "first as (select id from dataset_releases where organization_id=$1 and code=$2 "
            "          order by created_at limit 1), "
            "base as (select id from base0 union all "
            "         select id from first where not exists (select 1 from base0)) "
            "select canonical_field_code as c from dataset_release_fields "
            "where dataset_release_id in (select id from base) "
            "union "
            "select distinct v.canonical_field_code from dataset_values v "
            "where v.dataset_release_id in (select b.id from base b where not exists "
            "      (select 1 from dataset_release_fields f where f.dataset_release_id = b.id))",
            org_id, code, since)
        base = {r["c"] for r in base_rows}
        reviewed = set(reviewed_all.get(code) or [])
        cand = numeric - named - base - reviewed
        if not cand:
            continue
        titles = {r["code"]: r["name"] for r in await conn.fetch(
            "select code, name from canonical_fields where object_id=$1", latest["object_id"])}
        sep = pick_separator([n for n in titles.values() if n]) or " · "
        firsts = {r["c"]: r["p"] for r in await conn.fetch(
            "select f.canonical_field_code as c, min(r.reporting_period_start) as p "
            "from dataset_release_fields f join dataset_releases r on r.id = f.dataset_release_id "
            "where r.organization_id=$1 and r.code=$2 and f.canonical_field_code = any($3::text[]) "
            "group by 1", org_id, code, list(cand))}
        for c in cand:
            name = titles.get(c) or c
            if is_unnamed(name):
                continue
            covered = list(whole.get(code, []))
            if not is_total_column(name):
                covered += [wn for m, wn in measures.get(code, [])
                            if _levels.measure_of_name(name, sep) == m]
            out.append({"code": c, "name": name, "dataset_code": code,
                        "first_period": firsts.get(c), "covered_by": covered})
    out.sort(key=lambda f: (f["dataset_code"], f["name"]))
    return {"fields": out, "count": len(out)}


async def review_missing_fields(conn, org_id, dashboard_id: str, fields: List[dict]) -> dict:
    """«Больше не предлагать» — отметить графы просмотренными у этого дашборда.

    Отметка дашборда, а не формы: другой дашборд на той же форме может
    захотеть эту графу показать. Снять отметку из интерфейса нельзя — вывести
    отклонённую графу можно обычным конструктором виджета; выключение и
    включение подсказок отметок не сбрасывает.
    """
    cur = await conn.fetchval(
        "select fields_reviewed from dashboards where id=$1::uuid and organization_id=$2",
        dashboard_id, org_id)
    if cur is None:
        raise DashboardError("Дашборд не найден")
    reviewed: Dict[str, List[str]] = {k: list(v) for k, v in _cfg(cur).items()}
    added = 0
    for f in fields:
        code, field = f.get("dataset_code"), f.get("code")
        if not code or not field:
            continue
        lst = reviewed.setdefault(code, [])
        if field not in lst:
            lst.append(field)
            added += 1
    if added:
        await conn.execute(
            "update dashboards set fields_reviewed=$2::jsonb where id=$1::uuid",
            dashboard_id, json.dumps(reviewed, ensure_ascii=False))
    return {"reviewed": added}
