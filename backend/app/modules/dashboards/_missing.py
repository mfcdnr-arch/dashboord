"""Подсказка «💡 новые графы» на дашборде (этап 5, 01.10.2026; ревью 08.10.2026).

Форма прирастает графами, дашборд остаётся прежним, и узнать об этом можно было
только сверив их вручную. Подсказка была и раньше, но отвечала на другой вопрос
— «какой графы с числами не называет ни один виджет» — и на дашборде РЦО
насчитывала 359 таких из 384: туда попадали услуги, давно ушедшие из формы,
графы, показанные таблицей, и всё, что планировщик сознательно не вынес в
карточки при сборке. Подсказка, которая всегда говорит «359», не говорит ничего.

Теперь она отвечает на вопрос «что появилось в форме с тех пор, как дашборд
собрали»:
  • кандидаты — графы с числами в ПОСЛЕДНЕМ выпуске формы (не вся история);
  • минус графы, которые виджеты называют прямо (`_coverage.named_fields`), —
    своей формы: у двух форм коды граф могут совпасть;
  • минус «база дашборда» — графы выпусков с отчётным периодом не позже того,
    по который форма была на дашборде при сборке (`dashboard_form_since`,
    миграция 060): их видел тот, кто собирал дашборд, и выбрал сознательно.
    База — по ПЕРИОДУ, а не по времени создания: история, загруженная после
    сборки, тоже база («впервые в отчёте за 13.01» не может быть «появилась
    после сборки»), а перевыпуск, перенос данных и удаление ранних виджетов
    базу не сдвигают;
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


async def _forms_of(conn, dashboard_id: str) -> Dict[str, object]:
    """Формы дашборда и период, по который каждая была на нём при сборке."""
    widgets = await conn.fetch("select config from widgets where dashboard_id=$1::uuid", dashboard_id)
    codes: List[str] = []
    for w in widgets:
        for c in _coverage.dataset_codes(_cfg(w["config"])):
            if c not in codes:
                codes.append(c)
    since = {r["code"]: r["period"] for r in await conn.fetch(
        "select code, period from dashboard_form_since where dashboard_id=$1::uuid", dashboard_id)}
    return {c: since.get(c) for c in sorted(codes)}


async def missing_dashboard_fields(conn, org_id, dashboard_id: str) -> dict:
    """Новые с момента сборки графы форм дашборда, которых нет ни в одном виджете."""
    d = await conn.fetchrow(
        "select fields_reviewed from dashboards where id=$1::uuid and organization_id=$2",
        dashboard_id, org_id)
    if d is None:
        return {"fields": [], "count": 0, "reviewed": 0}
    reviewed_all = _cfg(d["fields_reviewed"])
    widgets = await conn.fetch(
        "select name, widget_type, config from widgets where dashboard_id=$1::uuid", dashboard_id)

    named: set = set()
    # (имя виджета, прячет ли он нули) — «уже видна в …» не должна обещать
    # графу, которую виджет не рисует.
    whole: Dict[str, List[tuple]] = {}
    measures: Dict[str, List[tuple]] = {}
    for w in widgets:
        cfg = _cfg(w["config"])
        named.update(_coverage.named_fields(cfg))
        own = cfg.get("dataset_code")
        if own and _coverage.reads_whole_form(w["widget_type"], cfg):
            whole.setdefault(own, []).append((w["name"], _coverage.hides_zero(w["widget_type"], cfg)))
        m = _coverage.measure_of_cfg(cfg)
        if own and m:
            measures.setdefault(own, []).append((m, w["name"]))

    forms = await _forms_of(conn, dashboard_id)
    reviewed_count = sum(len(reviewed_all.get(c) or []) for c in forms)
    out: List[dict] = []
    for code, since in forms.items():
        latest = await conn.fetchrow(
            "select id, object_id from dataset_releases "
            "where organization_id=$1 and code=$2 and status <> 'superseded' "
            "order by reporting_period_start desc nulls last, created_at desc limit 1",
            org_id, code)
        if latest is None:
            continue
        # Графы с числами и, отдельно, с ненулевым числом — второе нужно
        # «Показателям списком», которые нули прячут.
        numeric: set = set()
        nonzero: set = set()
        for r in await conn.fetch(
                "select canonical_field_code as c, bool_or(value_number <> 0) as nz from dataset_values "
                "where dataset_release_id=$1 and value_number is not null group by 1", latest["id"]):
            numeric.add(r["c"])
            if r["nz"]:
                nonzero.add(r["c"])
        # База: графы выпусков по период сборки включительно, любого статуса и
        # времени создания. Дашборд собран раньше любого выпуска формы (шаблон,
        # ручная сборка до данных) — базой служит первый выпуск по периоду,
        # иначе «новой» оказалась бы вся форма.
        #
        # Графы базы — по объявлениям выпуска, а у выпусков без объявлений (их
        # писали в обход штатного пути до 23.09) — по значениям. Значения
        # читаем ТОЛЬКО у таких выпусков: у РЦО в базе две сотни отчётов по
        # двадцать тысяч значений, и чтение всех сделало бы подсказку тяжёлой.
        base_rows = await conn.fetch(
            "with base0 as (select id from dataset_releases where organization_id=$1 and code=$2 "
            "                 and $3::date is not null and reporting_period_start <= $3::date), "
            "first as (select id from dataset_releases where organization_id=$1 and code=$2 "
            "          order by reporting_period_start nulls last, created_at limit 1), "
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
        own_named = {f for c, f in named if c == code}
        cand = numeric - own_named - base - reviewed
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
            covered = [wn for wn, hz in whole.get(code, []) if not hz or c in nonzero]
            if not is_total_column(name):
                covered += [wn for m, wn in measures.get(code, [])
                            if _levels.measure_of_name(name, sep) == m]
            out.append({"code": c, "name": name, "dataset_code": code,
                        "first_period": firsts.get(c), "covered_by": covered})
    out.sort(key=lambda f: (f["dataset_code"], f["name"]))
    return {"fields": out, "count": len(out), "reviewed": reviewed_count}


async def review_missing_fields(conn, org_id, dashboard_id: str, fields: List[dict]) -> dict:
    """«Больше не предлагать» — отметить графы просмотренными у этого дашборда.

    Отметка дашборда, а не формы: другой дашборд на той же форме может
    захотеть эту графу показать. Отмечается только то, что подсказка сейчас
    действительно предлагает: произвольные пары не попадают в отметки (иначе
    их раздувал бы любой запрос, а журнал аудита копировал бы раздутое при
    каждой правке дашборда). Снять отметки — `reset_reviewed_fields`.

    Чтение и запись — под блокировкой строки дашборда: два одновременных
    «Больше не предлагать» (две вкладки, два модератора) иначе затёрли бы
    отметки друг друга, и графа молча вернулась бы в подсказку.
    """
    async with conn.transaction():
        cur = await conn.fetchval(
            "select fields_reviewed from dashboards where id=$1::uuid and organization_id=$2 for update",
            dashboard_id, org_id)
        if cur is None:
            raise DashboardError("Дашборд не найден")
        offered = {(f["dataset_code"], f["code"])
                   for f in (await missing_dashboard_fields(conn, org_id, dashboard_id))["fields"]}
        reviewed: Dict[str, List[str]] = {k: list(v) for k, v in _cfg(cur).items()}
        added = 0
        for f in fields:
            code, field = str(f.get("dataset_code") or ""), str(f.get("code") or "")
            if (code, field) not in offered:
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


async def reset_reviewed_fields(conn, org_id, dashboard_id: str) -> dict:
    """«Вернуть скрытые графы» — снять все отметки «больше не предлагать».

    Без этого отметка была необратимой: нажатое по ошибке «Больше не
    предлагать 7 граф» прятало их навсегда, а вернуть можно было только правкой
    базы — против правила «управление через интерфейс».
    """
    cur = await conn.fetchval(
        "select fields_reviewed from dashboards where id=$1::uuid and organization_id=$2",
        dashboard_id, org_id)
    if cur is None:
        raise DashboardError("Дашборд не найден")
    n = sum(len(v or []) for v in _cfg(cur).values())
    if n:
        await conn.execute("update dashboards set fields_reviewed='{}'::jsonb where id=$1::uuid", dashboard_id)
    return {"returned": n}
