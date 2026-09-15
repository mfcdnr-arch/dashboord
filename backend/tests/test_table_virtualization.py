"""Виртуализация широкой таблицы: инварианты, которые нельзя потерять.

Тест читает исходники фронта — тот же приём, что у `test_widget_registry_consistency`
и `test_widget_card_box_sizing`. Здесь он оправдан тем, что ошибка в этих местах
НЕ падает и не видна на узких таблицах: она проявится только на форме в 327 граф,
то есть у заказчика на боевом, а не на стенде разработчика.

Замеры, ради которых виртуализация появилась (живой дашборд РЦО):
  • было 21 648 ячеек `<td>` и 23 040 узлов DOM — таблица составляла 94 % страницы;
  • сортировка кликом по заголовку не уложилась в 45 секунд и была прервана;
  • стало 990 ячеек, 2 069 узлов, сортировка 25–28 мс, поиск 15 мс.
"""
from __future__ import annotations

from pathlib import Path

import pytest

FRONT = Path("/frontend/src")
if not FRONT.exists():  # локальный прогон вне контейнера
    FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"

WIDGET_VIEW = FRONT / "components" / "WidgetView.tsx"
HOOK = FRONT / "lib" / "useVirtualCols.ts"


@pytest.fixture(scope="module")
def view() -> str:
    return WIDGET_VIEW.read_text(encoding="utf-8")


def test_v_otchete_virtualizatsiya_vyklyuchena(view: str):
    """🔴 В PDF прокрутки нет — там таблица обязана рисоваться целиком.

    Виртуализация показывает только то, что попало в окно; в отчёте окна нет,
    и половина граф просто не попала бы в файл. Человек при этом ничего бы не
    заметил: страницы выглядели бы заполненными.
    """
    assert "const virtOn = !print" in view, \
        "виртуализация должна быть выключена в режиме отчёта (print)"


def test_rasporki_est_i_v_shapke_i_v_strokakh(view: str):
    """🔴 Распорка только с одной стороны развела бы заголовки со значениями.

    Ширину невидимых колонок держат пустые ячейки по краям окна. Есть они в
    шапке, но нет в строках — и числа поедут под чужие заголовки: таблица
    останется правдоподобной с виду и будет врать.
    """
    head_pads = view.count("vcols.range.padBefore > 0 && <th")
    body_pads = view.count("vcols.range.padBefore > 0 && <td")
    assert head_pads >= 1, "нет распорки в шапке"
    assert body_pads >= 1, "нет распорки в строках — значения съедут под чужие заголовки"
    assert view.count("vcols.range.padAfter > 0 && <th") >= 1
    assert view.count("vcols.range.padAfter > 0 && <td") >= 1


def test_shapka_i_stroki_rezhutsya_odnim_oknom(view: str):
    """Шапка и строки обязаны показывать ОДИН и тот же диапазон колонок."""
    cuts = view.count("cols.slice(vcols.range.start, vcols.range.end)")
    assert cuts == 2, f"окно колонок применяется {cuts} раз вместо двух (шапка + строки)"


def test_shirina_kolonok_zadana_pri_virtualizatsii(view: str):
    """Без фиксированной ширины нельзя посчитать, какая колонка попала в кадр."""
    assert "tableLayout: 'fixed'" in view
    assert "VCOL_FIRST_W + cols.length * VCOL_W" in view, \
        "полная ширина таблицы должна считаться по ВСЕМ колонкам — иначе до дальних граф не доскроллить"


def test_porog_vklyucheniya_imenovannyy():
    """Порог живёт константой рядом с хуком, а не числом внутри разметки."""
    src = HOOK.read_text(encoding="utf-8")
    assert "export const VIRT_FROM_COLS" in src
    value = int(src.split("VIRT_FROM_COLS = ")[1].split("\n")[0].strip())
    # Ниже порога вид таблицы не меняется вовсе; выше — начинается выигрыш.
    assert 10 <= value <= 60, f"порог {value} выглядит случайным"


def test_okno_schitaetsya_chistoy_funktsiey():
    """Расчёт вынесен из компонента — иначе его нельзя проверить тестом."""
    assert (FRONT / "lib" / "virtual.ts").exists()
    assert (FRONT / "lib" / "virtual.test.ts").exists(), \
        "у расчёта видимого окна должны быть свои тесты"
