"""Календарь поступлений формы: год плитками по неделям (п. 16).

Папка — это одна форма, которая приходит раз за разом. Ответ на вопрос «за
какие недели отчёт есть, а за какие нет» до сих пор существовал только
текстом: аналитика папки пишет «не хватает отчётов за 29.07.2026». Строка
верна, но она не отвечает на вопрос ГЛАЗАМИ — за год таких строк набирается
десяток, и увидеть в них сезон или полосу пропусков нельзя.

Календарь показывает тот же факт плиткой: неделя — клетка, цвет — состояние.

**Ничего не считается заново.** Ритм берётся той же `infer_cadence`, что шлёт
уведомления о пропущенном отчёте, а сами пропуски — той же `missing_periods`,
что печатает аналитика папки строкой. Разойдись они — и красная плитка
означала бы пропуск, о котором соседний экран молчит.

**Ритм считается по ВЫПУСКАМ, а не по файлам** — по тем же периодам, что и в
аналитике папки, чтобы на одном экране не оказалось двух разных ответов на
вопрос «как часто приходит форма». Следствие честное: пока выпусков мало и
ритм не признан, пропуски не отмечаются вовсе — лучше промолчать, чем
раскрасить полгода красным из-за формы, которая приходит как придётся.

**Плитка показывает самое дальнее состояние, но не прячет проблему.** Если в
неделе два файла и один выпущен, а второй не распознан, плитка зелёная —
иначе выпущенные данные выглядели бы отсутствующими; но у неё стоит угловая
метка проблемы, а подсказка перечисляет оба файла поимённо.
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from ..maintenance.service import infer_cadence, missing_periods


class CalendarError(Exception):
    pass


# Состояния плитки в порядке «дальше по конвейеру». Плитке достаётся
# максимальное из состояний её файлов.
_RANK = {"empty": 0, "missing": 1, "failed": 2, "arrived": 3, "released": 4}


def _iso_weeks(year: int) -> int:
    """Сколько ISO-недель в году: 52 или 53. 28 декабря по стандарту всегда
    лежит в последней неделе года — это и есть самый короткий способ узнать."""
    return date(year, 12, 28).isocalendar()[1]


async def folder_calendar(conn, org_id, folder_id: str, year: Optional[int] = None) -> dict:
    folder = await conn.fetchrow(
        "select f.id, f.name, f.object_id, o.name as object_name "
        "from folders f left join objects o on o.id=f.object_id "
        "where f.id=$1::uuid and f.organization_id=$2", folder_id, org_id)
    if folder is None:
        raise CalendarError("Папка не найдена")

    docs = await conn.fetch(
        "select d.id, d.original_filename, d.reporting_period_start as period, "
        "  (select j.status::text from extraction_jobs j "
        "   join document_versions v2 on v2.id=j.document_version_id "
        "   where v2.document_id=d.id order by j.created_at desc limit 1) as job_status, "
        "  exists(select 1 from dataset_releases r "
        "         join document_versions v3 on v3.id=r.source_document_version_id "
        "         where v3.document_id=d.id and r.status <> 'superseded') as released "
        "from documents d where d.folder_id=$1::uuid "
        "order by d.reporting_period_start", folder_id)

    # Ритм — по выпускам, как и в аналитике папки (см. докстроку модуля).
    release_periods = await conn.fetch(
        "select distinct r.reporting_period_start as period "
        "from dataset_releases r join document_versions v on v.id=r.source_document_version_id "
        "join documents d on d.id=v.document_id "
        "where d.folder_id=$1::uuid and r.organization_id=$2 and r.status <> 'superseded' "
        "  and r.reporting_period_start is not null", folder_id, org_id)
    periods = sorted(r["period"] for r in release_periods)
    cadence = infer_cadence(periods)

    today: date = await conn.fetchval("select current_date")
    gaps = missing_periods(periods, cadence, until=today) if cadence else []

    # Годы, по которым вообще есть что показать. Год без единого отчёта в
    # список не попадает — переключатель не должен предлагать пустые экраны.
    # Годы — ISO-годы дат, а не календарные: отчёт за 30.12.2025 по ISO лежит
    # в первой неделе 2026-го и виден в СЕТКЕ 2026 года. Предложи мы 2025-й,
    # человек открыл бы пустой экран и решил, что отчёт потерялся.
    years = sorted({d["period"].isocalendar()[0] for d in docs if d["period"]}
                   | {p.isocalendar()[0] for p in periods}
                   | {g.isocalendar()[0] for g in gaps})
    if not years:
        years = [today.year]
    if year is None:
        # По умолчанию — год последнего отчёта, а не текущий: если форму
        # перестали присылать в прошлом декабре, открывать пустой этот год
        # значит показать человеку «ничего нет» вместо его данных.
        year = years[-1]
    if year not in years:
        years = sorted({*years, year})

    weeks: List[dict] = []
    index: dict = {}
    for w in range(1, _iso_weeks(year) + 1):
        start = date.fromisocalendar(year, w, 1)
        cell = {
            # Месяц недели — по ЧЕТВЕРГУ, а не по понедельнику. Первая неделя
            # года начинается ещё в декабре предыдущего (у 2026-го — 29.12.2025),
            # и по понедельнику она попала бы в декабрьский ряд, встав там
            # первой: месяц открывался бы числом 29, за которым идёт 7.
            # Четверг — стандартное ISO-правило принадлежности недели.
            "week": w, "month": date.fromisocalendar(year, w, 4).month,
            "start": start.isoformat(),
            "end": date.fromisocalendar(year, w, 7).isoformat(),
            "state": "empty", "problem": False,
            "reports": [], "missing": [],
        }
        weeks.append(cell)
        index[w] = cell

    def _cell(d: date):
        """Клетка, которой принадлежит дата. По ISO-календарю: конец декабря
        может относиться к первой неделе следующего года и наоборот — тогда
        дата просто не попадает в этот год, и это правильно."""
        iso = d.isocalendar()
        return index.get(iso[1]) if iso[0] == year else None

    undated = 0
    for d in docs:
        if d["period"] is None:
            undated += 1
            continue
        cell = _cell(d["period"])
        if cell is None:
            continue
        failed = d["job_status"] == "failed"
        state = "released" if d["released"] else ("failed" if failed else "arrived")
        cell["reports"].append({
            "id": str(d["id"]), "filename": d["original_filename"],
            "period": d["period"].isoformat(), "released": d["released"],
            "status": d["job_status"], "state": state,
        })
        if _RANK[state] > _RANK[cell["state"]]:
            cell["state"] = state
        if failed:
            cell["problem"] = True

    for g in gaps:
        cell = _cell(g)
        if cell is None:
            continue
        cell["missing"].append(g.isoformat())
        # Файл в этой неделе всё же есть (отчёт сместился) — тогда пропуска
        # нет: неделя закрыта, и красить её было бы ложной тревогой.
        if not cell["reports"]:
            cell["state"] = "missing"

    totals = {k: sum(1 for c in weeks if c["state"] == k)
              for k in ("released", "arrived", "failed", "missing")}
    return {
        "folder": {"id": str(folder["id"]), "name": folder["name"],
                   "object_id": str(folder["object_id"]) if folder["object_id"] else None,
                   "object_name": folder["object_name"]},
        "year": year, "years": years, "today": today.isoformat(),
        "cadence_days": cadence,
        "weeks": weeks,
        "totals": {**totals, "undated": undated,
                   "reports": sum(len(c["reports"]) for c in weeks)},
    }
