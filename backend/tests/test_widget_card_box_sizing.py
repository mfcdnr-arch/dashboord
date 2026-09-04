"""Карточка виджета не должна переливаться за свою ячейку.

Высоту карточке задаёт РАСКЛАДКА: в «потоке» — height ячейки, в свободной
сетке react-grid-layout ставит height инлайном в пикселях. Глобального
`* { box-sizing: border-box }` в проекте нет, поэтому при content-box поля
карточки и рамка прибавляются СВЕРХУ к заданной высоте — замер на дашборде РЦО
дал ячейку 431px против карточки 461px (14+14 поля и 1+1 рамка). Перелив
выливался в следующий ряд и накладывался на соседей: ровно та жалоба, с
которой заказчик прислал снимок 04.09.2026. Величина зависит от плотности
(в компактном режиме поля 9 → перелив 20px), поэтому «подобрать высоту» нельзя.

Правило `.react-grid-item { box-sizing: border-box }` в теме это НЕ закрывает:
оно достаёт только до ПРЯМОГО потомка сетки, а с 22.08 карточка обёрнута
отдельным div — border-box получает пустая обёртка. Дефект так и вернулся,
поэтому инвариант держит тест, а не память.

Тот же приём, что в test_widget_registry_consistency, test_flow_layout_consistency
и test_alert_theme_tokens: дублирование в вёрстке честное, но расхождение ловим
тестом, а не в проде.
"""
import re
from pathlib import Path

FRONT = Path(__file__).resolve().parents[2] / "frontend/src"
BORDER_BOX = re.compile(r"boxSizing:\s*'border-box'")

# Каждое место, где рисуется карточка виджета, и чем оно является для человека.
CARDS = {
    "components/dashboards/WidgetCard.tsx": "карточка страницы дашборда",
    "components/PagePreview.tsx": "панель витрины и раздела «Витрины»",
    "components/KioskView.tsx": "полноэкранная «📺 Витрина»",
}


def test_every_card_declares_border_box():
    missing = [f"{p} ({what})" for p, what in CARDS.items()
               if not BORDER_BOX.search((FRONT / p).read_text(encoding="utf-8"))]
    assert not missing, ("Карточка без border-box переливается за свою ячейку и "
                         "накладывается на соседние: " + "; ".join(missing))


def test_page_preview_covers_both_layouts():
    """PagePreview рисует страницу ДВУМЯ способами — «потоком» и сеткой.

    Правка одной ветки оставила бы вторую с прежним дефектом, а увидеть это
    можно только открыв витрину: на дашборде обе выглядят одинаково.
    """
    src = (FRONT / "components/PagePreview.tsx").read_text(encoding="utf-8")
    assert len(BORDER_BOX.findall(src)) >= 2


def test_grid_rule_is_kept_as_a_fallback():
    """Правило в теме оставлено запасным.

    Оно ничего не стоит и снова заработает, если карточка когда-нибудь опять
    станет прямым потомком сетки. Убрать его — потерять защиту даром.
    """
    css = (FRONT / "theme.css").read_text(encoding="utf-8")
    assert re.search(r"\.react-grid-item\s*\{[^}]*box-sizing:\s*border-box", css)
