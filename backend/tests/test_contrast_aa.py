"""Контраст фирменных цветов: нормы WCAG AA, посчитанные из самой палитры.

Тест читает `theme.css` и считает контраст — тот же приём, что у
`test_widget_registry_consistency` и `test_modal_accessibility`. Здесь он
особенно уместен: контраст НЕ виден при обычной работе и не падает ни в
одном тесте — цвет просто тихо становится хуже читаемым, и замечает это
только тот, кому трудно читать.

Из чего выросло (аудит 15.09): белый текст на фирменной заливке давал
3,95 / 3,09 / 3,05 — ниже нормы во всех трёх темах; акцент в роли ТЕКСТА
на слабой подложке — 3,27 и 2,44.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONT = Path("/frontend/src")
if not FRONT.exists():  # локальный прогон вне контейнера
    FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"

THEME = FRONT / "theme.css"

# Норма WCAG 2.1: обычный текст 4.5:1, графика и крупный текст 3:1.
# Кнопки набраны 12–14px без полужирного — это обычный текст.
AA_TEXT = 4.5
AA_GRAPHIC = 3.0


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    parts = [int(h[i: i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in parts]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _themes() -> dict[str, dict[str, str]]:
    """Токены каждой темы: :root — светлая, затем блоки [data-theme=...]."""
    src = THEME.read_text(encoding="utf-8")
    out: dict[str, dict[str, str]] = {}
    # делим файл на блоки по селекторам верхнего уровня
    for m in re.finditer(r"(:root(?:\[data-theme=[\"']?(\w+)[\"']?\])?[^{]*)\{([^}]*)\}", src):
        name = m.group(2) or "light"
        body = m.group(3)
        tokens = dict(re.findall(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})", body))
        if not tokens:
            continue
        out.setdefault(name, {}).update(tokens)
    return out


@pytest.fixture(scope="module")
def themes() -> dict[str, dict[str, str]]:
    found = _themes()
    # Защита от вырождения: если разбор сломается, проверять станет нечего.
    assert set(found) >= {"light", "dark", "minek"}, f"темы не разобраны: {list(found)}"
    return found


def test_text_on_brand_fill_is_readable(themes) -> None:
    """Текст на фирменной кнопке — обычный текст, ему нужно 4,5:1."""
    bad = []
    for name, t in themes.items():
        got = contrast(t["accent"], t["on-accent"])
        if got < AA_TEXT:
            bad.append(f"{name}: --on-accent на --accent = {got:.2f}")
    assert not bad, "текст на фирменной кнопке ниже нормы AA: " + "; ".join(bad)


def test_text_on_danger_fill_is_readable(themes) -> None:
    """У danger свой токен текста: в «МинЭк» ему нужен белый, а акценту — тёмный.

    Пока обе роли делили `--on-accent`, одним значением их покрыть было нельзя.
    """
    bad = []
    for name, t in themes.items():
        assert "on-danger" in t, f"{name}: нет --on-danger — текст на danger возьмёт чужой токен"
        got = contrast(t["danger"], t["on-danger"])
        if got < AA_TEXT:
            bad.append(f"{name}: --on-danger на --danger = {got:.2f}")
    assert not bad, "текст на кнопке опасности ниже нормы AA: " + "; ".join(bad)


def test_accent_as_text_is_readable_on_both_surfaces(themes) -> None:
    """Акцент в роли ТЕКСТА читается и на карточке, и на своей подложке.

    Два фона проверяются вместе: цвет, подобранный только под белый, на
    акцентной подложке снова уходит ниже нормы — так и было (3,27).
    """
    bad = []
    for name, t in themes.items():
        assert "accent-text" in t, f"{name}: нет --accent-text"
        for bg_token in ("surface", "accent-weak-bg"):
            got = contrast(t["accent-text"], t[bg_token])
            if got < AA_TEXT:
                bad.append(f"{name}: --accent-text на --{bg_token} = {got:.2f}")
    assert not bad, "акцентный текст ниже нормы AA: " + "; ".join(bad)


def test_brand_fill_is_visible_against_page(themes) -> None:
    """Сама кнопка должна отличаться от страницы — это графика, норма 3:1.

    Держит вторую сторону: затемняя акцент ради текста на нём, легко
    получить кнопку, сливающуюся с фоном.
    """
    bad = []
    for name, t in themes.items():
        got = contrast(t["accent"], t["bg"])
        if got < AA_GRAPHIC:
            bad.append(f"{name}: --accent на --bg = {got:.2f}")
    assert not bad, "фирменная кнопка сливается с фоном страницы: " + "; ".join(bad)


def test_accent_is_not_used_as_text_in_components() -> None:
    """`--accent` — заливка; как цвет текста берётся `--accent-text`.

    Иначе следующий экран снова заведут с 3,95:1, и заметить это можно
    будет только замером.
    """
    offenders: list[str] = []
    for path in sorted((FRONT / "components").rglob("*.tsx")):
        if ".test." in path.name:
            continue
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"(?<![A-Za-z])color: *'var\(--accent\)'", src):
            line = src[: m.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(FRONT)}:{line}")
    assert not offenders, (
        "акцент использован как цвет текста — нужен --accent-text: " + ", ".join(offenders)
    )


# Поверхности, на которых реально рендерится приглушённый текст. Список не
# выдуман: замер по живому дереву (обход 8 разделов) показал --text-muted на
# пяти фонах, а --text-faint — на --surface и на --bg. Проверяем все пять, а
# не только белый: подбор «под карточку» на фоне страницы снова уходил ниже
# нормы, и ровно так дефект и жил.
SURFACES = ("surface", "surface-2", "surface-3", "accent-weak-bg", "bg")


def test_muted_text_is_readable_on_every_surface(themes) -> None:
    """Приглушённый текст — обычный текст, ему нужно 4,5:1 на КАЖДОМ фоне.

    До правки (прогон 17.09): --text-muted давал 3,95 на --surface-3 в светлой
    и 2,97 на --surface-2 в «МинЭк»; --text-faint — 2,58 / 3,85 / 1,69 на
    карточке. Этим цветом набраны кнопки виджета «⚑ проблема», «⤓ Excel»,
    «💬 замечание» и подпись формы под заголовком — то есть не декор.
    """
    bad = []
    for name, t in themes.items():
        for token in ("text-muted", "text-faint"):
            for bg in SURFACES:
                got = contrast(t[token], t[bg])
                if got < AA_TEXT:
                    bad.append(f"{name}: --{token} на --{bg} = {got:.2f}")
    assert not bad, "приглушённый текст ниже нормы AA: " + "; ".join(bad)


def test_muted_steps_stay_distinct(themes) -> None:
    """Обратная сторона: ступени серого не должны схлопнуться в одну.

    Если оба токена просто дотянуть до 4,5 на худшем фоне, они сходятся в
    один цвет, и третья ступень приглушённости перестаёт существовать —
    иерархия теряется там же, где чинился контраст.
    """
    bad = []
    for name, t in themes.items():
        lm, lf = _luminance(t["text-muted"]), _luminance(t["text-faint"])
        gap = abs(lm - lf) / max(lm, lf)
        if gap < 0.12:
            bad.append(f"{name}: --text-muted и --text-faint различаются на {gap * 100:.0f}%")
    assert not bad, "ступени приглушённого текста слились: " + "; ".join(bad)


def test_status_colors_are_readable(themes) -> None:
    """Статусные цвета несут смысл, значит подчиняются норме для текста.

    Проверяются обе поверхности: сам цвет стоит и на карточке («↑ +467 %»),
    и на своей подложке («API: ok»). До правки --success давал 3,99 и 3,46 в
    светлой, --warn — 4,18 на своей подложке в «МинЭк».
    """
    bad = []
    for name, t in themes.items():
        for token in ("success", "warn", "danger"):
            for bg in ("surface", f"{token}-bg"):
                got = contrast(t[token], t[bg])
                if got < AA_TEXT:
                    bad.append(f"{name}: --{token} на --{bg} = {got:.2f}")
    assert not bad, "статусный цвет ниже нормы AA: " + "; ".join(bad)


def test_focus_ring_is_not_suppressed_in_components() -> None:
    """`outline: 'none'` инлайном гасит фокусное кольцо браузера.

    Так и было у столбиков графика «Входы по дням»: выбранный получал свой
    outline, а остальные 24 — `none`, то есть идущий клавиатурой не видел,
    где он. Состояние выбора помечается чем угодно ещё (фон, inset-тень),
    но не outline.
    """
    offenders: list[str] = []
    for path in sorted(FRONT.rglob("*.tsx")):
        if ".test." in path.name:
            continue
        src = path.read_text(encoding="utf-8")
        # Ловим и прямое 'none', и тернарник '… ? … : "none"'. Отрицательный
        # просмотр '(?!\w+ *:)' не даёт уйти в СЛЕДУЮЩЕЕ свойство: иначе
        # 'outline: …, background: "none"' считалось бы нарушением.
        for m in re.finditer(r"outline:(?:(?!\w+ *:)[^\n])*'none'", src):
            line = src[: m.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(FRONT)}:{line}")
    assert not offenders, (
        "фокусное кольцо подавлено инлайновым outline: 'none' — "
        "выбор помечайте фоном или inset-тенью: " + ", ".join(offenders)
    )
