"""Уровни порогов на сервере и цвета этих уровней в темах не должны разойтись.

Сервер считает УРОВЕНЬ (danger/poor/warn/good) — это правило, одно на систему.
Каким цветом уровень нарисован, решает ТЕМА (`frontend/src/theme.css`): раньше
цвета приезжали вместе с уровнем жёсткими hex, одной палитрой на все темы, и в
тёмной теме залитая ячейка светилась светлым маркером на тёмном фоне.

Тот же приём, что в test_widget_registry_consistency и
test_flow_layout_consistency: держим дублирование честным, ловя расхождение
тестом, а не в проде. Если на сервере появится пятая ступень, тест напомнит
добавить ей цвета во ВСЕ темы.
"""
import re
from pathlib import Path

from app.modules.dashboards._alerts import _ALERT_STYLES

FRONT = Path(__file__).resolve().parents[2] / "frontend/src/theme.css"
HELPER = Path(__file__).resolve().parents[2] / "frontend/src/lib/alertColors.ts"
# Сколько тем в файле: светлая, тёмная и «МинЭк».
THEMES = 3


def test_every_level_has_colors_in_every_theme():
    css = FRONT.read_text(encoding="utf-8")
    for level in _ALERT_STYLES:
        for suffix in ("", "-bg"):
            token = f"--alert-{level}{suffix}:"
            found = css.count(token)
            assert found == THEMES, (
                f"{token} задан в {found} темах из {THEMES} — в остальных порог "
                f"нарисуется серверным цветом не по теме")


def test_frontend_helper_knows_the_same_levels():
    src = HELPER.read_text(encoding="utf-8")
    m = re.search(r"ALERT_LEVELS = \[([^\]]+)\]", src)
    assert m, "не нашли список уровней в lib/alertColors.ts — переехал файл?"
    front = {x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()}
    assert front == set(_ALERT_STYLES), (
        f"уровни разошлись: на сервере {sorted(_ALERT_STYLES)}, на фронте {sorted(front)}")


def test_light_theme_keeps_the_previous_server_colors():
    """У того, кто работает в светлой теме, вид не должен измениться."""
    css = FRONT.read_text(encoding="utf-8")
    light = css[: css.index('[data-theme="dark"]')]
    for level, st in _ALERT_STYLES.items():
        assert f"--alert-{level}: {st['color']};" in light, f"{level}: цвет текста разошёлся со старым"
        assert f"--alert-{level}-bg: {st['bg']};" in light, f"{level}: подложка разошлась со старой"
