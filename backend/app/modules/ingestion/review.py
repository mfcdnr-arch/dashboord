"""Проверка качества по ВСЕЙ истории формы, а не по последнему отчёту.

Проверки качества в системе есть с 15.08, но увидеть их можно было ровно в
двух местах, и оба смотрят на ОДИН отчёт: модератор — на тот, что выпускает, а
блок «На что посмотреть» — на последний активный. Поэтому вопрос «а по всей
истории где расходится?» не имел ответа вовсе: расхождение итоговой графы,
найденное 22.09.2026 на 54 отчётах из 201, пришлось искать разовым скриптом.

Своих правил здесь нет намеренно — считает та же `check_release`, что и оба
других места. Иначе экран истории однажды назвал бы замечанием то, о чём
модератор при выпуске молчал, и верить нельзя было бы обоим.

Что проверяется и что НЕТ — сказано прямо, потому что разница существенная:
проверяется АРИФМЕТИКА ВЫПУЩЕННЫХ значений (сумма против итога, неделя против
накопительного, факт против плана, сверка с прошлым отчётом). Замечания к
разбору файла (строки без названия, нераспознанные числа) считаются по сетке
исходного листа в момент выпуска, а её к этому времени может уже не быть —
сюда они не попадают.
"""
from __future__ import annotations

from typing import Optional

from .quality import check_release, previous_release_values

# Сколько отчётов проверяем по умолчанию и максимум за один раз. Проверка
# читает значения КАЖДОГО отчёта целиком (у широкой формы это двадцать тысяч
# строк), поэтому «проверить всё» — осознанный выбор человека, а не умолчание.
DEFAULT_LIMIT = 30
MAX_LIMIT = 400

# Заголовок замечания — короткий, для свода «по каким правилам расходится».
# Подробности с числами остаются в самом сообщении правила.
TITLES = {
    "total_row_mismatch": "Итоговая строка не сходится с суммой строк",
    "total_row_in_data": "Итоговая строка попала в данные",
    "total_column_mismatch": "Итоговая графа не сходится с суммой составляющих",
    "weekly_over_total": "За неделю больше, чем накопительным итогом",
    "fact_over_plan": "Факт превышает план",
    "all_zeros": "Форма заполнена, а работы в ней нет",
    "almost_empty": "Отчёт почти пустой",
    "cumulative_drop": "Накопительный итог уменьшился",
    "same_as_previous": "Данные совпадают с прошлым отчётом",
    "plan_changed": "План изменился задним числом",
    "multiplied_by_factor": "Показатели умножены на один коэффициент",
    "quality_checks_failed": "Проверки качества не отработали",
}


async def _values(conn, release_id) -> dict:
    rows = await conn.fetch(
        "select row_label, canonical_field_code, value_number from dataset_values "
        "where dataset_release_id=$1 and value_number is not null", release_id)
    return {(r["row_label"] or "", r["canonical_field_code"]): float(r["value_number"])
            for r in rows}


async def quality_review(conn, org_id, object_id, code: Optional[str] = None,
                         limit: int = DEFAULT_LIMIT) -> dict:
    """Свод замечаний по истории одной формы: по каким правилам и в какие даты.

    Отчёты обходятся в ХРОНОЛОГИЧЕСКОМ порядке, и значения каждого становятся
    «прошлым» для следующего: иначе на каждый отчёт приходилось бы по два
    чтения вместо одного, а на двух сотнях широких отчётов это разница между
    полуминутой и минутой с лишним.

    Самому раннему отчёту окна предшественник дочитывается отдельно — без него
    первый отчёт каждого окна проверялся бы «без прошлого», и сдвиг окна менял
    бы вердикт по одним и тем же данным.
    """
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    if not code:
        code = await conn.fetchval(
            "select code from dataset_releases where organization_id=$1 and object_id=$2 "
            "and status<>'superseded' group by code "
            "order by count(*) desc, max(reporting_period_start) desc limit 1",
            org_id, object_id)
    if not code:
        return {"code": None, "checked": 0, "total": 0, "clean": 0, "issues": [], "items": []}

    total = await conn.fetchval(
        "select count(*) from dataset_releases where organization_id=$1 and code=$2 "
        "and object_id=$3 and status<>'superseded' and reporting_period_start is not null",
        org_id, code, object_id)
    rows = await conn.fetch(
        "select id, reporting_period_start as period from dataset_releases "
        "where organization_id=$1 and code=$2 and object_id=$3 and status<>'superseded' "
        "and reporting_period_start is not null "
        "order by reporting_period_start desc limit $4", org_id, code, object_id, limit)
    releases = list(reversed(rows))
    if not releases:
        return {"code": code, "checked": 0, "total": total or 0, "clean": 0,
                "issues": [], "items": []}

    names = {r["code"]: r["name"] for r in await conn.fetch(
        "select code, name from canonical_fields where object_id=$1", object_id)}

    prev, prev_period = await previous_release_values(
        conn, org_id, code, releases[0]["period"])

    items: list[dict] = []
    issues: dict[str, dict] = {}
    clean = 0
    for rel in releases:
        current = await _values(conn, rel["id"])
        warnings = check_release(current, names, prev, prev_period) if current else []
        period = rel["period"].isoformat()
        if warnings:
            items.append({"period": period, "release_id": str(rel["id"]),
                          "warnings": warnings})
            for w in warnings:
                agg = issues.setdefault(w["code"], {
                    "code": w["code"], "title": TITLES.get(w["code"], w["code"]),
                    "releases": 0, "periods": [], "example": w.get("message")})
                agg["releases"] += 1
                agg["periods"].append(period)
        else:
            clean += 1
        prev, prev_period = current, rel["period"].strftime("%d.%m.%Y")

    for agg in issues.values():
        # Даты показываем СВЕЖИЕ: разбирают обычно с последнего отчёта, а
        # полное число уже названо рядом.
        agg["periods"] = sorted(agg["periods"], reverse=True)[:20]

    return {
        "code": code,
        "total": total or 0,
        "checked": len(releases),
        "clean": clean,
        "first_period": releases[0]["period"].isoformat(),
        "last_period": releases[-1]["period"].isoformat(),
        "issues": sorted(issues.values(), key=lambda x: (-x["releases"], x["code"])),
        # Поимённо — чтобы можно было открыть конкретный отчёт, а не искать его
        # по своду. Ограничение по свежести: длинный список никто не читает.
        "items": items[::-1][:50],
    }
