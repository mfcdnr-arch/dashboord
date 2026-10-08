"""Русское склонение по числу: 1 строка, 2 строки, 5 строк, 11 строк.

Одна функция на весь бэкенд. До 08.10.2026 она жила тремя копиями
(`metrics/describe`, `dashboards/_describe`, `dashboards/_widgetexport`) и
отдельной `_plural_rows`; копии были записаны по-разному, и расходиться
начали бы ровно в тексте, который читает человек.
"""


def plural(n: int, one: str, few: str, many: str) -> str:
    """Ловушка — 11–14: «11 строк», а не «11 строка»; знак числа не важен."""
    tail = abs(int(n)) % 100
    if 11 <= tail <= 14:
        return many
    last = tail % 10
    return one if last == 1 else few if 2 <= last <= 4 else many
