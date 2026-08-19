"""Имена листов Excel: 31 знак — жёсткий предел, а имена госформ втрое длиннее.

Проверяем не «красиво», а три обязательных свойства: лист можно ОТЛИЧИТЬ от
соседнего, имя укладывается в предел и не содержит запрещённых Excel знаков.
"""
import pytest

from app.modules.dashboards._sheetnames import LIMIT, sheet_titles

DYN = "Динамика: Количество {} · Факт · {}"
NAMES = [
    DYN.format("обращений за результатом оказания услуг в МФЦ", "нарастающим итогом**"),
    DYN.format("обращений за результатом оказания услуг в МФЦ", "нарастающим итогом (текущий месяц)"),
    DYN.format("обращений за результатом оказания услуг в МФЦ", "за отчетную неделю"),
    DYN.format("пользователей, записавшихся на приём", "за отчетную неделю"),
    "Внедрение сервиса МАХ: таблица",
]


def test_titles_fit_are_unique_and_legal():
    t = sheet_titles(NAMES)
    assert len(set(x.lower() for x in t)) == len(NAMES)      # листы различимы
    assert all(len(x) <= LIMIT for x in t)                   # предел Excel
    assert all(not set(x) & set("[]:*?/\\") for x in t)      # запрещённые знаки


def test_common_part_is_dropped_so_the_difference_shows():
    # Прежняя обрезка слева давала «Динамика  Количество обращ 2/3/4»: и
    # показатель, и разрез терялись. Теперь общее для группы начало уходит, а
    # в имени остаётся то, ради чего лист открывают.
    t = sheet_titles(NAMES)
    assert "Динамика" not in t[0]
    assert "обращений" in t[0] and "итогом" in t[0]
    assert "пользователей" in t[3] and "неделю" in t[3]
    # Три разреза одного показателя различаются именно разрезом, а не цифрой.
    assert "(текущий месяц)" in t[1]
    assert "неделю" in t[2]


def test_identical_names_still_give_different_sheets():
    # Два виджета можно назвать одинаково — файл всё равно обязан открыться.
    t = sheet_titles(["Отчёт", "Отчёт", "Отчёт"])
    assert len(set(t)) == 3


def test_short_name_survives_intact():
    assert sheet_titles(["Таблица"]) == ["01 Таблица"]


@pytest.mark.parametrize("bad", ["А/Б", "План: факт", "Итог*", "[итого]", "Что?"])
def test_forbidden_characters_are_removed(bad):
    assert not set(sheet_titles([bad])[0]) & set("[]:*?/\\")
