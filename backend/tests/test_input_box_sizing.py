"""Поле ввода во всю ширину не должно вылезать за край своего блока.

Глобального `* { box-sizing: border-box }` в проекте нет (см.
test_widget_card_box_sizing), а браузеры по умолчанию делают border-box только
у `<select>` — у `<input>` и `<textarea>` content-box. Поэтому поле со
`width: '100%'` и внутренними отступами шире своего блока ровно на отступы и
рамку: 10+10 и 1+1 — 22px. Нашлось съёмкой кадра для руководства 30.09.2026: в
мастере «✨ Собрать» список «Куда собрать» стоял ровно, а поле «Название» под
ним торчало за край и теряло правую рамку. Тот же дефект сидел ещё в восьми
местах («О дашборде», «Настройки», «Метрики», разметка, модерация, форма
виджета).

Глобальное правило для всех полей отвергнуто: у ~300 полей с заданной высотой
оно сдвинуло бы высоту на 2px, а заметить это можно только глазами. Правка
точечная, а держит её этот страж — тот же приём, что у остальных тестов,
читающих исходники фронта.
"""
import re
from pathlib import Path

FRONT = Path(__file__).resolve().parents[2] / "frontend/src"
FULL = re.compile(r"width:\s*'100%'")
BORDER_BOX = re.compile(r"boxSizing:\s*'border-box'")
# Тег поля целиком: атрибуты бывают на нескольких строках.
# `>` стрелки `=>` внутри обработчика тег не закрывает.
TAG = re.compile(r"<(input|textarea)\b(.*?)(?<!=)>", re.S)
INLINE_STYLE = re.compile(r"style=\{\{(.*?)\}\}", re.S)
NAMED_STYLE = re.compile(r"style=\{(\w+)\}")


def _const_style(src: str, name: str) -> str:
    m = re.search(rf"const {name}\b[^=]*=\s*\{{(.*?)\}}\n", src, re.S)
    return m.group(1) if m else ""


def _offenders(src: str):
    for tag in TAG.finditer(src):
        attrs = tag.group(2)
        if re.search(r"type=\"(checkbox|radio|file|color|range)\"", attrs):
            continue
        style = ""
        inline = INLINE_STYLE.search(attrs)
        if inline:
            style = inline.group(1)
            # `...input` — дочитываем разворачиваемый стиль того же файла.
            for spread in re.findall(r"\.\.\.(\w+)", style):
                style += " " + _const_style(src, spread)
        else:
            named = NAMED_STYLE.search(attrs)
            if named:
                style = _const_style(src, named.group(1))
        if FULL.search(style) and not BORDER_BOX.search(style):
            yield src.count("\n", 0, tag.start()) + 1


def test_full_width_fields_are_border_box():
    bad = []
    for path in sorted(FRONT.rglob("*.tsx")):
        src = path.read_text(encoding="utf-8")
        for line in _offenders(src):
            bad.append(f"{path.relative_to(FRONT)}:{line}")
    assert not bad, ("Поле со width: '100%' без boxSizing: 'border-box' вылезает за край "
                     "блока на свои отступы и рамку: " + ", ".join(bad))


def test_guard_sees_both_forms():
    """Страж обязан ловить и инлайновый стиль, и стиль-константу.

    Иначе он молча перестанет проверять одну из форм записи — на этом уже
    спотыкались стражи доступности (журнал 17.09).
    """
    inline = "<input style={{ ...input, width: '100%' }} value={x} />\nconst input = { height: 34 }\n"
    named = "const inp: React.CSSProperties = { width: '100%', padding: 8 }\n<textarea style={inp} />"
    assert list(_offenders(inline)) and list(_offenders(named))
    fixed = "<input style={{ width: '100%', boxSizing: 'border-box' }} />"
    assert not list(_offenders(fixed))
