"""Доступность модальных окон: инварианты, которые нельзя потерять.

Тест читает исходники фронта — тот же приём, что у
`test_widget_registry_consistency` и `test_table_virtualization`. Здесь он
оправдан тем, что поломка НЕ падает и не видна глазами: окно выглядит и
работает мышью ровно так же, а человек с клавиатуры и диктор экрана
оказываются в ловушке — попасть в окно можно, выйти нельзя.

Из чего выросло (аудит 15.09.2026): из 38 окон `role="dialog"` стоял у
ОДНОГО, ловушки фокуса не было ни у одного, Escape не закрывал 26.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONT = Path("/frontend/src")
if not FRONT.exists():  # локальный прогон вне контейнера
    FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"

MODAL = FRONT / "components" / "Modal.tsx"
TRAP = FRONT / "lib" / "focusTrap.ts"
PALETTE = FRONT / "components" / "CommandPalette.tsx"

# Полноэкранный режим витрины (слайд-шоу страниц на ТВ) — не диалог: из него
# выходят кнопкой и Escape, а «фона», к которому надо вернуться, у него нет.
NOT_A_DIALOG = {"KioskView.tsx"}

# Общие стили затемнения и окна: их ОПРЕДЕЛЯЕТ shared.tsx, а применяет
# единственный владелец — Modal. Само определение нарушением не является.
STYLE_SOURCE = {"shared.tsx"}


@pytest.fixture(scope="module")
def modal() -> str:
    return MODAL.read_text(encoding="utf-8")


def tsx_files() -> list[Path]:
    return sorted((FRONT / "components").rglob("*.tsx"))


def test_modal_announces_itself_to_screen_reader(modal: str) -> None:
    """Без role/aria-modal/имени диктор не сообщит, куда человек попал."""
    assert "role: 'dialog' as const" in modal or 'role="dialog"' in modal
    assert "'aria-modal': true" in modal
    assert "'aria-label': label" in modal


def test_modal_traps_focus_and_closes_by_escape(modal: str) -> None:
    """Ловушка фокуса и Escape — то, без чего окно становится ловушкой."""
    assert "focusablesIn" in modal, "Tab уводил бы за окно"
    assert "nextIndex" in modal
    assert "e.key === 'Escape'" in modal
    assert "onClose()" in modal


def test_modal_returns_focus_to_the_opener(modal: str) -> None:
    """Иначе после закрытия фокус падает в начало страницы."""
    assert "openerRef" in modal
    assert "isConnected" in modal, "исчезнувшей кнопке фокус возвращать нельзя"


def test_only_the_topmost_modal_reacts_to_keys(modal: str) -> None:
    """Стек: один Escape не должен закрывать сразу два вложенных окна."""
    assert "const stack" in modal
    assert "stack[stack.length - 1] !== id" in modal


def test_modal_renders_through_portal(modal: str) -> None:
    """Портал в body — окно не обрезается карточкой и сеткой дашборда.

    Ровно ради этого порталы и заводились (09.08 и 24.08); обёртка обязана
    сохранить свойство, а не вернуть окно внутрь трансформированной сетки.
    """
    assert "createPortal(" in modal
    assert "document.body" in modal


def test_focus_trap_logic_lives_apart_from_the_component() -> None:
    """Расчёт вынесен в чистый модуль: внутри компонента его не проверить."""
    src = TRAP.read_text(encoding="utf-8")
    assert "export function focusablesIn" in src
    assert "export function nextIndex" in src
    assert 'tabindex="-1"' in src, "элемент вне Tab-порядка не должен попасть в цикл"


def test_no_dialog_builds_its_own_overlay() -> None:
    """Новое окно обязано идти через <Modal>, а не собирать оверлей заново.

    Собранное вручную окно доступность получает случайно — так и вышло, что
    из 38 окон её имело одно. Тест держит единственную точку входа.
    """
    offenders: list[str] = []
    for path in tsx_files():
        if path.name in NOT_A_DIALOG | STYLE_SOURCE or path.name == "Modal.tsx":
            continue
        src = path.read_text(encoding="utf-8")
        # затемнение во весь экран = модальное окно
        for m in re.finditer(r"position: 'fixed', inset: 0[^\n}]*background: 'rgba\(", src):
            line = src[: m.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(FRONT)}:{line}")
    assert not offenders, (
        "окна собраны в обход <Modal> — у них не будет ни ловушки фокуса, ни Escape: "
        + ", ".join(offenders)
    )


def test_every_window_names_itself() -> None:
    """У окна должно быть имя: без него диктор объявит безымянный диалог.

    Имя даётся одним из двух способов: <ModalTitle> с видимым заголовком
    (предпочтительно — текст пишется один раз) либо проп `label` там, где
    видимого заголовка нет вовсе (меню действий, окно из одних кнопок).
    """
    nameless: list[str] = []
    total = 0
    for path in tsx_files():
        if path.name.endswith(".test.tsx"):
            continue
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r"<Modal\b", src):
            total += 1
            # тело окна: от открывающего тега до его закрытия
            end = src.find("</Modal>", m.end())
            body = src[m.end(): end if end > 0 else m.end() + 600]
            head = src[m.end(): m.end() + 400]
            has_label = re.match(r"[\s\S]{0,300}?\blabel=", head)
            has_title = "<ModalTitle" in body
            if not (has_label or has_title):
                nameless.append(f"{path.relative_to(FRONT)}:{src[: m.start()].count(chr(10)) + 1}")
    assert not nameless, (
        "окна без имени — диктор объявит безымянный диалог: " + ", ".join(nameless)
    )
    # Защита от вырождения теста: если окна вдруг «исчезли», проверять нечего.
    assert total >= 30, f"окон найдено {total} — тест перестал что-либо проверять"


def test_title_is_not_duplicated_as_aria_label() -> None:
    """Имя и видимый заголовок — одна строка, а не две копии.

    Пока текст стоит и в `aria-label`, и в разметке, правка одного оставляет
    второй позади — и расходится ровно то, что читает диктор.
    """
    modal = MODAL.read_text(encoding="utf-8")
    assert "'aria-labelledby': titleId" in modal
    assert "hasTitle ?" in modal, "при наличии заголовка label использоваться не должен"
    assert "export function ModalTitle" in modal
    assert "<h2" in modal, "заголовок окна должен быть заголовком, а не div"


def test_background_is_frozen_while_a_window_is_open() -> None:
    """Фон под окном недоступен ни Tab, ни диктору в режиме чтения.

    Замораживается то, что лежало в body на момент открытия, — не body
    целиком: подсказки ⓘ и облачка графиков рисуются порталами тоже в body,
    и открытые ИЗ окна появляются позже, под заморозку не попадая.
    """
    modal = MODAL.read_text(encoding="utf-8")
    assert "setAttribute('inert'" in modal
    assert "removeAttribute('inert')" in modal
    assert "!el.hasAttribute('inert')" in modal, (
        "чужую заморозку снимать нельзя: у вложенных окон каждое отвечает за своё"
    )


def test_command_palette_is_a_list_not_just_a_window() -> None:
    """Быстрый поиск: диктор должен читать выбранную строку, а не молчать.

    Фокус в палитре остаётся в поле ввода (иначе стрелки и Tab спорят за
    управление), поэтому выбранную строку диктору сообщает
    `aria-activedescendant`, а сам список размечен как listbox.
    """
    src = PALETTE.read_text(encoding="utf-8")
    assert 'role="combobox"' in src
    assert 'role="listbox"' in src
    assert 'role="option"' in src
    assert "aria-activedescendant" in src, "иначе диктор не назовёт выбранную строку"
    assert "aria-selected" in src
    assert 'aria-live="polite"' in src, "число найденного надо сообщать вслух"
