"""Проверки качества данных перед выпуском: сверка с прошлой неделей.

Форму заполняет человек, и самые дорогие ошибки — не опечатки, а перенос
прошлых цифр. Реальный случай заказчика (05.08.2026): строка «Донецкая Народная
Республика» в новом отчёте совпала с отчётом за 29.07 посимвольно — данные
неделю не обновляли, а система приняла их молча и показала на дашборде как
свежие.

Проверки НЕ блокируют выпуск: решение за человеком, а ошибочный выпуск в
системе обратим («Отменить выпуск»). Задача — не дать пропустить подозрительное
молча. Поэтому все правила формулируются как «проверьте», а не «нельзя».

Правила опираются на устройство имён госформ («Показатель · Роль · Разрез»),
разбор которых уже живёт в metrics/data_suggestions — переиспользуем его, чтобы
система не противоречила сама себе.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from ..metrics.data_suggestions import _clean, _is_main_slice, _split_name, _subject_key

# Ключ значения: (название строки, код показателя)
Key = Tuple[str, str]


def classify_slice(field_name: str) -> str:
    """Разрез показателя: cumulative | weekly | other.

    «Нарастающим итогом» — накопление с начала периода: такое значение по
    определению не может уменьшиться. «За отчётную неделю» — срез, он всегда
    часть накопленного. Остальное (например «текущий месяц») не сравниваем:
    месячный накопительный итог законно падает при смене месяца.
    """
    slc = _clean(_split_name(field_name)["slice"]).lower()
    if "недел" in slc:
        return "weekly"
    if _is_main_slice(slc):
        return "cumulative"
    return "other"


def _fmt(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ") if float(v).is_integer() else f"{v:,.2f}".replace(",", " ")


def compare_with_previous(
    current: Dict[Key, float],
    previous: Dict[Key, float],
    names: Dict[str, str],
    previous_period: Optional[str] = None,
    partial: bool = False,
) -> List[dict]:
    """Сравнение готовящегося выпуска с предыдущим. Чистая функция, без БД.

    `partial` — сравнивается НЕ вся форма, а только часть строк (так бывает на
    дашборде, где действует RLS по строкам). Тогда «все данные совпадают»
    означает «все ДОСТУПНЫЕ вам строки»: без этой оговорки человек с одной
    разрешённой строкой решил бы, что не обновилась вся форма.
    """
    warnings: List[dict] = []
    if not previous:
        return warnings

    period_txt = f" за {previous_period}" if previous_period else ""

    # ── 1. Накопительный итог не может уменьшиться ────────────────────────────
    drops: List[str] = []
    for key, cur in current.items():
        prev = previous.get(key)
        if prev is None or classify_slice(names.get(key[1], "")) != "cumulative":
            continue
        if cur < prev:
            drops.append(f"«{names.get(key[1], key[1])}» в строке «{key[0]}»: было {_fmt(prev)}, стало {_fmt(cur)}")
    if drops:
        warnings.append({
            "code": "cumulative_drop", "count": len(drops),
            "message": ("Накопительный итог уменьшился — так не бывает, если это тот же показатель: "
                        + "; ".join(drops[:5])),
        })

    # ── 2. Значение за неделю не больше накопительного итога ──────────────────
    # Пары ищем по показателю: у одной графы «за отчётную неделю» есть графа
    # «нарастающим итогом» того же показателя.
    cum_by_subject: Dict[str, str] = {}
    for code, name in names.items():
        if classify_slice(name) == "cumulative":
            cum_by_subject.setdefault(_subject_key(_split_name(name)["subject"]), code)

    over: List[str] = []
    for key, cur in current.items():
        name = names.get(key[1], "")
        if classify_slice(name) != "weekly":
            continue
        cum_code = cum_by_subject.get(_subject_key(_split_name(name)["subject"]))
        if cum_code is None:
            continue
        total = current.get((key[0], cum_code))
        if total is not None and cur > total:
            over.append(f"«{name}» в строке «{key[0]}»: за неделю {_fmt(cur)} при итоге {_fmt(total)}")
    if over:
        warnings.append({
            "code": "weekly_over_total", "count": len(over),
            "message": ("Значение за неделю больше накопительного итога — похоже, графы перепутаны местами: "
                        + "; ".join(over[:5])),
        })

    # ── 3. Данные совпадают с прошлой неделей ────────────────────────────────
    # Считаем ПОСТРОЧНО, а не по выпуску целиком: у заказчика совпала ровно одна
    # строка, а в форме была ещё одна — сравнение «весь файл целиком» такой
    # случай пропустило бы.
    rows_now = {k[0] for k in current}
    same_rows = []
    for row in sorted(rows_now):
        cells = {k[1]: v for k, v in current.items() if k[0] == row}
        prev_cells = {k[1]: v for k, v in previous.items() if k[0] == row}
        if not cells or not prev_cells:
            continue
        if set(cells) == set(prev_cells) and all(prev_cells[f] == v for f, v in cells.items()):
            same_rows.append(row)
    if same_rows:
        whole = len(same_rows) == len(rows_now)
        all_txt = ("Все доступные вам строки совпадают с прошлым выпуском" if partial
                   else "Все данные совпадают с прошлым выпуском")
        head = (all_txt if whole
                else f"Совпадают с прошлым выпуском строки: {', '.join(f'«{r}»' for r in same_rows[:5])}")
        warnings.append({
            "code": "same_as_previous", "count": len(same_rows),
            "message": (f"{head}{period_txt} — проверьте, не перенесены ли цифры прошлой недели "
                        "без обновления."),
        })

    # ── 4. Плановое значение не должно меняться от отчёта к отчёту ───────────
    # План задаётся на СРОК («до 1 сентября»), поэтому в еженедельной форме он
    # обязан повторяться неизменным. Если он растёт каждую неделю — в графу
    # «План» почти наверняка попадает факт из другого источника, и тогда
    # «выполнение плана» на дашборде считается сам с собой. Найдено осмотром
    # данных заказчика: план по записавшимся шёл 38 992 → 38 992 → 40 552 →
    # 41 971 при неизменном сроке.
    moved: List[str] = []
    for key, cur in current.items():
        prev = previous.get(key)
        if prev is None or prev == cur:
            continue
        name = names.get(key[1], "")
        if _split_name(name).get("role") != "plan":
            continue
        moved.append(f"«{name}» в строке «{key[0]}»: было {_fmt(prev)}, стало {_fmt(cur)}")
    if moved:
        warnings.append({
            "code": "plan_changed", "count": len(moved),
            "message": ("Плановое значение изменилось с прошлого отчёта — план задаётся на срок и "
                        "меняться не должен; проверьте, не попал ли в графу «План» факт: "
                        + "; ".join(moved[:5])),
        })

    return warnings


def values_from_rows(rows: Sequence[Sequence[str]], fields: Sequence[dict],
                     label_col: Optional[int]) -> Dict[Key, float]:
    """Числовые значения размеченной таблицы в виде {(строка, поле): число}."""
    from . import analyze

    out: Dict[Key, float] = {}
    for row in rows:
        label = str(row[label_col]) if label_col is not None and label_col < len(row) else ""
        for f in fields:
            if f.get("is_row_label") or f.get("data_type") != "number":
                continue
            ci = f["column_index"]
            num = analyze.parse_number(row[ci] if ci < len(row) else "")
            if num is not None:
                out[(label, f["field_code"])] = num
    return out


async def previous_release_values(conn, org_id, code: str, before_period) -> tuple:
    """Значения последнего активного выпуска этого кода ДО указанного периода.

    Сравнивать надо с предыдущей неделей, а не с выпуском за тот же период:
    повторный выпуск за ту же дату — это исправление, и совпадение с ним
    ожидаемо. Возвращает ({(строка, поле): число}, дата выпуска-источника).
    """
    rel = await conn.fetchrow(
        "select id, reporting_period_start from dataset_releases "
        "where organization_id=$1 and code=$2 and status <> 'superseded' "
        "  and ($3::text is null or reporting_period_start < $3::text::date) "
        "order by reporting_period_start desc nulls last, created_at desc limit 1",
        org_id, code, str(before_period) if before_period else None)
    if rel is None:
        return {}, None
    rows = await conn.fetch(
        "select row_label, canonical_field_code, value_number from dataset_values "
        "where dataset_release_id=$1 and value_number is not null", rel["id"])
    values = {(r["row_label"] or "", r["canonical_field_code"]): float(r["value_number"]) for r in rows}
    period = rel["reporting_period_start"]
    return values, (period.strftime("%d.%m.%Y") if period else None)
