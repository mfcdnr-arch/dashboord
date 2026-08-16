"""Формула → человеческое описание показателя (2026-08-09).

Заказчик: «можешь в поле „расширенная информация о показателе“ автоматически
включать основную информацию, а модератор уже поправит или добавит».

Поле info_text видит КОНЕЧНЫЙ пользователь в окне «🔍 подробнее». Раньше оно
почти всегда оставалось пустым («Информации нет, в разработке»), потому что
писать его нужно было руками. Здесь текст собирается из того, что система и так
знает: разобранной формулы, имён столбцов, единицы измерения, состояния версии
и того, как часто обновляются данные.

Текст — ЧЕРНОВИК: он подставляется в поле, но не сохраняется молча. Сохраняет
модератор, предварительно проверив и дополнив.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

_AGG_RU = {
    "SUM": "сумма значений",
    "AVG": "среднее значение",
    "MIN": "наименьшее значение",
    "MAX": "наибольшее значение",
    "COUNT": "количество заполненных строк",
}
_UNIT_RU = {"month": "месяц", "quarter": "квартал", "year": "год", "week": "неделя", "day": "день"}
_PREV_RU = {"month": "прошлым месяцем", "quarter": "прошлым кварталом", "year": "прошлым годом",
            "week": "прошлой неделей", "day": "прошлым днём",
            # 'first' — не шаг назад, а начало ряда: назвать это «прошлым
            # периодом» значило бы подписать показатель неверно.
            "first": "первым периодом данных"}


def _plural(n: int, one: str, few: str, many: str) -> str:
    """Русское склонение после числа: 1 период, 2 периода, 5 периодов."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _col(names: Dict[str, str], code: str) -> str:
    """Человеческое имя столбца; если справочника нет — сам код в кавычках."""
    return f"«{names.get(code, code)}»"


def describe_ast(ast: Dict[str, Any], names: Optional[Dict[str, str]] = None) -> str:
    """Разобранная формула → фраза по-русски. Рекурсивно, как и вычисление."""
    names = names or {}
    t = ast.get("t")

    if t == "num":
        v = ast["v"]
        return str(int(v)) if float(v).is_integer() else str(v)
    if t == "field":
        return _col(names, ast["field"])
    if t == "cell":
        return f"ячейка {_col(names, ast['col'])} в строке «{ast['row']}»"
    if t == "metric":
        return f"показатель «{ast['code']}»"
    if t == "agg":
        inner = describe_ast(ast["arg"], names)
        base = f"{_AGG_RU.get(ast['fn'], ast['fn'])} по столбцу {inner}"
        filt = ast.get("filter")
        if filt and filt.get("row"):
            base += f" (только строка «{filt['row']}»)"
        return base
    if t == "neg":
        return f"минус {describe_ast(ast['e'], names)}"
    if t == "pow":
        return f"{describe_ast(ast['base'], names)} в степени {describe_ast(ast['exp'], names)}"
    if t == "bin":
        op = {"+": "плюс", "-": "минус", "*": "умножить на", "/": "разделить на"}.get(ast["op"], ast["op"])
        return f"{describe_ast(ast['l'], names)} {op} {describe_ast(ast['r'], names)}"
    if t == "percent_of":
        return (f"{describe_ast(ast['value'], names)} — сколько это процентов от "
                f"{describe_ast(ast['base'], names)} (база = 100 %)")
    if t == "plan_fact":
        plan, fact = describe_ast(ast["plan"], names), describe_ast(ast["fact"], names)
        if ast.get("fn") == "PLAN_FACT_PCT":
            return f"выполнение плана в процентах: факт ({fact}) к плану ({plan})"
        return f"отклонение факта ({fact}) от плана ({plan}) в единицах показателя"
    if t == "running_total":
        return f"накопительный итог по всем периодам: {describe_ast(ast['arg'], names)}"
    if t == "period_compare":
        mode = ast.get("mode", "delta")
        how = {"delta": "разница в единицах показателя", "pct": "в процентах к прошлому периоду",
               "ratio": "во сколько раз"}.get(mode, mode)
        return (f"сравнение с {_PREV_RU.get(ast.get('unit', 'month'), 'прошлым периодом')} "
                f"({how}): {describe_ast(ast['arg'], names)}")
    if t == "share":
        return f"доля последнего периода в сумме по всем периодам: {describe_ast(ast['arg'], names)}"
    return "расчёт по формуле"


def build_info_draft(*, metric_name: str, formula: str, ast: Optional[Dict[str, Any]],
                     unit: Optional[str], status: Optional[str], datasets: list,
                     field_names: Optional[Dict[str, str]] = None,
                     periods: int = 0, last_period: Optional[str] = None) -> str:
    """Черновик расширенной информации: что считает, откуда, как часто, как читать."""
    lines = [f"{metric_name} — что показывает."]

    if ast:
        lines.append(f"Расчёт: {describe_ast(ast, field_names)}.")
    lines.append(f"Формула: {formula}")

    if datasets:
        lines.append("Источник данных: " + ", ".join(f"«{d}»" for d in datasets) + ".")

    if periods > 1:
        lines.append(f"Обновление: данные загружены за {periods} {_plural(periods, 'период', 'периода', 'периодов')}"
                     + (f", последний — {last_period}." if last_period else "."))
    elif last_period:
        lines.append(f"Обновление: пока один период данных ({last_period}).")

    if unit:
        lines.append(f"Единица измерения: {unit}.")
    if unit == "%":
        lines.append("Как читать: значение в процентах; 100 % — база достигнута полностью.")

    state = {"approved": "одобрена ответственным сотрудником",
             "validated": "проверена автором, ждёт одобрения",
             "draft": "черновик — значение может измениться"}.get(status or "", None)
    if state:
        lines.append(f"Состояние формулы: {state}.")

    lines.append("")
    lines.append("— текст подготовлен системой; дополните его смыслом показателя, "
                 "ответственным подразделением и особенностями учёта.")
    return "\n".join(lines)
