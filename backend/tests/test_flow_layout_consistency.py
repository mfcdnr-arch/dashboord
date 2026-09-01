"""Согласованность раскладок backend↔frontend.

Авто-сборка расставляет виджеты по таблице `_suggest.WIDGET_SIZE` (свободная
сетка), а режим «поток» пересчитывает раскладку при отрисовке по
`frontend/src/lib/flowLayout.ts`. Размеры там намеренно РАЗНЫЕ: в сетке график
занимает ряд целиком (дальше человек двигает его сам), в потоке — половину,
иначе страница из трёх десятков виджетов остаётся лентой.

Совпадать обязано другое, и это ловит тест:
 • «поток» знает КАЖДЫЙ тип виджета, иначе новый вид молча получит запасной
   размер и встанет не туда;
 • класс «широкое» (таблицы и текст — во всю ширину) один и тот же в обеих
   раскладках: если таблица окажется в половине ряда, она уйдёт в
   горизонтальную прокрутку и перестанет читаться.

Тот же приём, что в test_widget_registry_consistency: держим дублирование
честным, ловя расхождение тестом, а не в проде.
"""
import re
from pathlib import Path

from app.modules.dashboards._base import ANNOTATION_TYPES, WIDGET_TYPES
from app.modules.dashboards._suggest import WIDGET_SIZE

FRONTEND_FILE = Path(__file__).resolve().parents[2] / "frontend/src/lib/flowLayout.ts"
FULL_WIDTH = {"table", "pivot", "matrix", "text", "spark_table"}


def _frontend_sizes() -> dict[str, tuple[int, int]]:
    src = FRONTEND_FILE.read_text(encoding="utf-8")
    block = src[src.index("export const FLOW_SIZE"):src.index("export const FLOW_FALLBACK")]
    return {m[0]: (int(m[1]), int(m[2]))
            for m in re.findall(r"(\w+):\s*\{\s*w:\s*(\d+),\s*h:\s*(\d+)\s*\}", block)}


def test_flow_knows_every_widget_type():
    front = _frontend_sizes()
    assert front, "не нашли ни одного размера в flowLayout.ts — сломался regex или файл переехал?"
    missing = sorted(WIDGET_TYPES - set(front))
    assert not missing, f"в «потоке» нет размеров для типов {missing} — они встанут по запасному правилу"


def test_full_width_class_matches_between_layouts():
    front = _frontend_sizes()
    front_wide = {t for t, s in front.items() if s[0] == 12}
    assert front_wide == FULL_WIDTH, f"в «потоке» во всю ширину идут {sorted(front_wide)}, ожидали {sorted(FULL_WIDTH)}"
    # В свободной сетке таблицы тоже занимают ряд целиком.
    for t in FULL_WIDTH & set(WIDGET_SIZE):
        assert WIDGET_SIZE[t][0] == 12, f"{t}: в сетке ширина {WIDGET_SIZE[t][0]}, а в потоке 12 — раскладки разойдутся"


def test_fallback_exists_for_unknown_type():
    src = FRONTEND_FILE.read_text(encoding="utf-8")
    assert "FLOW_FALLBACK" in src, "убрали запасной размер — новый тип виджета сломает «поток»"


def test_annotation_widgets_are_present():
    """Текст и картинка — тоже виджеты страницы, «поток» обязан их разместить."""
    front = _frontend_sizes()
    assert ANNOTATION_TYPES <= set(front)
