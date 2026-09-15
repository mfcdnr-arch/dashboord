"""Таблицы доступны с клавиатуры: инварианты, которые нельзя потерять.

Тест читает исходники фронта — тот же приём, что у
`test_modal_accessibility` и `test_table_virtualization`. Здесь он оправдан
тем, что поломка не видна ни глазами, ни мышью: таблица выглядит и работает
как прежде, а человек с клавиатуры просто не может ни отсортировать, ни
провалиться в строку — самые частые действия на главном экране разбора цифр.

Из чего выросло (аудит 15.09.2026): сортировка была `<th onClick>`,
проваливание — `<tr onClick>`; Tab по ним не ходит вовсе, и диктор не
сообщал ни что столбец сортируем, ни в каком он порядке.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONT = Path("/frontend/src")
if not FRONT.exists():  # локальный прогон вне контейнера
    FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"

PARTS = FRONT / "components" / "TableParts.tsx"


@pytest.fixture(scope="module")
def parts() -> str:
    return PARTS.read_text(encoding="utf-8")


def test_sorting_is_a_button_with_announced_order(parts: str) -> None:
    """Кнопка — чтобы работали Enter и пробел; aria-sort — чтобы диктор
    знал текущий порядок: стрелку ▲ рядом с текстом он не увидит."""
    assert "aria-sort={dir}" in parts
    assert "'ascending'" in parts and "'descending'" in parts
    assert "<button" in parts


def test_row_drill_is_a_button_too(parts: str) -> None:
    """Проваливание в строку — кнопка на названии, а не `tr` с onClick."""
    assert "export function RowPickCell" in parts
    assert 'scope="row"' in parts, "заголовок строки ведёт диктора по таблице"
    assert "Показать всю страницу по строке" in parts


def test_toggle_rows_announce_their_state(parts: str) -> None:
    """Раскрытие и фильтр — разные состояния, и оба надо назвать вслух."""
    assert "'aria-expanded': expanded" in parts
    assert "'aria-pressed': pressed" in parts


def test_no_table_relies_on_click_only() -> None:
    """Новая таблица обязана брать общие части, а не вешать onClick на th/tr.

    `<th onClick>` и `<tr onClick>` недостижимы с клавиатуры: Tab по ним не
    ходит. Тест держит единственную точку входа — как со окнами.
    """
    offenders: list[str] = []
    for path in sorted((FRONT / "components").rglob("*.tsx")):
        if path.name.endswith(".test.tsx"):
            continue
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"<th\b[^>]*\sonClick=", src, re.S):
            offenders.append(f"{path.relative_to(FRONT)}:{src[: m.start()].count(chr(10)) + 1} (th)")
    assert not offenders, (
        "заголовки сортируются только мышью — возьмите <SortableTh>: " + ", ".join(offenders)
    )


def test_clickable_rows_keep_a_keyboard_path() -> None:
    """У кликабельной строки должен быть клавиатурный путь в первой ячейке.

    Сам `<tr onClick>` оставлен намеренно — мышью привычно попадать в любое
    место строки; но рядом обязана быть ячейка-кнопка, иначе с клавиатуры
    строка недостижима.
    """
    bad: list[str] = []
    for path in sorted((FRONT / "components").rglob("*.tsx")):
        if path.name.endswith(".test.tsx"):
            continue
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"<tr\b[^>]*\sonClick=", src, re.S):
            end = src.find("</tr>", m.end())
            row = src[m.end(): end if end > 0 else m.end() + 1200]
            if "RowPickCell" not in row and "RowToggleCell" not in row:
                bad.append(f"{path.relative_to(FRONT)}:{src[: m.start()].count(chr(10)) + 1}")
    assert not bad, (
        "строку можно выбрать только мышью — добавьте <RowPickCell>/<RowToggleCell>: "
        + ", ".join(bad)
    )
