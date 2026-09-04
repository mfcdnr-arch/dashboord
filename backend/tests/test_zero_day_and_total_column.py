"""Два правила, найденных на данных заказчика 04.09.2026.

① «Форма заполнена, а работы нет» (`all_zeros`). 28.08.2026 у ежедневного
отчёта РЦО заполнено 20 212 клеток — столько же, сколько накануне, — но
ненулевых из них 42, по услугам ноль, а в «ИТОГО · Принято» единица. Соседняя
проверка `almost_empty` такой день пропускает ПО УСТРОЙСТВУ: она считает
ЗАПОЛНЕННЫЕ клетки, а ноль — заполненная. Цена пропуска высокая: виджет читает
последний выпуск, и весь дашборд показывает нули, а человек видит не «день
пустой», а «система сломалась».

② Итоговая ГРАФА против суммы составляющих (`total_column_mismatch`) — зеркало
уже имевшейся сверки итоговой СТРОКИ. Форма РЦО состоит из неё целиком.

Числа в тестах настоящие, снятые с выпусков стенда: синтетика здесь слабее,
оба правила целиком про реальный разброс.
"""
import pytest

from app.modules.ingestion import quality


def _grid(rows, codes, value):
    """Прямоугольник rows × codes, заполненный одним значением."""
    return {(r, c): value for r in rows for c in codes}


# ─────────────────────────── ① день из нулей ────────────────────────────────

def test_filled_form_without_work_is_reported():
    """28.08 в масштабе: клеток много, ненулевых почти нет."""
    rows = [f"Отделение {i}" for i in range(62)]
    codes = [f"f{i}" for i in range(326)]
    current = _grid(rows, codes, 0.0)
    # 42 ненулевых из 20 212 — доля 0,21 %, как в настоящем выпуске.
    for i, key in enumerate(list(current)[:42]):
        current[key] = float(i + 1)

    w = quality._check_all_zeros(current)
    assert w and w["code"] == "all_zeros"
    assert w["count"] == 42
    # Замечание обязано назвать ОБА числа: одно «42» не говорит, много это или
    # мало, а вся суть правила — в их соотношении.
    assert "42" in w["message"] and str(len(current)) in w["message"]
    # И объяснить последствие, а не только факт.
    assert "нули" in w["message"]


def test_sparse_but_working_form_stays_quiet():
    """«Статистика услуг — Росимущество»: 5 ненулевых из 248 — это норма.

    Ведомство оказывает услуги в единицах отделений. Сработай правило здесь —
    его приучились бы пролистывать, и оно перестало бы работать вообще.
    """
    rows = [f"Отделение {i}" for i in range(62)]
    codes = ["a", "b", "c", "d"]
    current = _grid(rows, codes, 0.0)
    for key in list(current)[:5]:
        current[key] = 3.0
    assert len(current) == 248
    assert quality._check_all_zeros(current) is None


def test_short_but_real_day_stays_quiet():
    """Короткая суббота 29.08: 573 ненулевых из 10 874 — рабочий день."""
    rows = [f"Отделение {i}" for i in range(62)]
    codes = [f"f{i}" for i in range(175)]
    current = _grid(rows, codes, 0.0)
    for key in list(current)[:573]:
        current[key] = 1.0
    assert quality._check_all_zeros(current) is None


def test_small_form_is_not_judged_by_share():
    """На мелкой форме доля скачет от одной клетки — правило молчит.

    Заодно это граница с `almost_empty`: лист-заготовка (186 клеток) — это
    «клеток почти нет», и о нём говорит ТА проверка. Одно событие — одно
    замечание.
    """
    current = _grid(["Республика"], [f"f{i}" for i in range(13)], 0.0)
    assert quality._check_all_zeros(current) is None


def test_zero_day_reaches_the_release_through_check_release():
    """Правило доезжает до обеих точек входа, а не живёт само по себе."""
    rows = [f"Отделение {i}" for i in range(62)]
    codes = [f"f{i}" for i in range(326)]
    current = _grid(rows, codes, 0.0)
    current[(rows[0], codes[0])] = 1.0
    names = {c: f"Ведомство · Услуга {c} · Принято, ед." for c in codes}

    codes_seen = {w["code"] for w in quality.check_release(current, {}, names)}
    assert "all_zeros" in codes_seen


# ──────────────────── ② итоговая графа против суммы ─────────────────────────

NAMES_RCO = {
    "itogo_acc": "ИТОГО · Принято, ед.",
    "ros_acc": "Росреестр · Выписка из ЕГРН · Принято, ед.",
    "esia_acc": "ЕСИА (260) · Принято, ед.",
    "itogo_iss": "ИТОГО · Выдано, ед.",
    "ros_iss": "Росреестр · Выписка из ЕГРН · Выдано, ед.",
    "esia_iss": "ЕСИА (260) · Выдано, ед.",
}


def test_total_column_mismatch_is_found():
    """Волноваха 27.08: «ИТОГО · Принято» = 1 при сумме услуг 125."""
    current = {
        ("Волноваха", "itogo_acc"): 1.0,
        ("Волноваха", "ros_acc"): 100.0,
        ("Волноваха", "esia_acc"): 25.0,
    }
    w = quality._check_total_column(current, NAMES_RCO)
    assert w and w["code"] == "total_column_mismatch"
    assert "Волноваха" in w["message"]
    assert "125" in w["message"] and "расхождение" in w["message"]


def test_total_column_tolerates_rounding():
    """Расхождение в единицу — округление, а не ошибка."""
    current = {
        ("Горловка", "itogo_acc"): 125.0,
        ("Горловка", "ros_acc"): 100.0,
        ("Горловка", "esia_acc"): 25.5,
    }
    assert quality._check_total_column(current, NAMES_RCO) is None


def test_stages_of_one_request_are_not_summed_together():
    """«Принято» и «Выдано» — разные группы, их суммы не смешиваются.

    Сложи их в одну — и обращение сосчиталось бы дважды, а правило выдавало бы
    расхождение на каждой строке каждой формы.
    """
    current = {
        ("Донецк", "itogo_acc"): 125.0, ("Донецк", "ros_acc"): 100.0, ("Донецк", "esia_acc"): 25.0,
        ("Донецк", "itogo_iss"): 300.0, ("Донецк", "ros_iss"): 200.0, ("Донецк", "esia_iss"): 100.0,
    }
    assert quality._check_total_column(current, NAMES_RCO) is None


def test_rule_is_silent_when_form_does_not_name_its_structure():
    """Нет « · » в именах — устройство формы неизвестно, гадать нельзя."""
    names = {"itogo": "ИТОГО", "a": "Услуга А", "b": "Услуга Б"}
    current = {("Донецк", "itogo"): 1.0, ("Донецк", "a"): 100.0, ("Донецк", "b"): 25.0}
    assert quality._check_total_column(current, names) is None


def test_shares_are_not_summed():
    """Доли не складываются — правило одно на систему (`_aggregate.is_share`)."""
    names = {
        "itogo_pct": "ИТОГО · Доля доставленных, %",
        "a_pct": "Росреестр · Выписка · Доля доставленных, %",
        "b_pct": "ЕСИА · Доля доставленных, %",
    }
    current = {("Донецк", "itogo_pct"): 50.0, ("Донецк", "a_pct"): 40.0, ("Донецк", "b_pct"): 60.0}
    assert quality._check_total_column(current, names) is None


@pytest.mark.parametrize("codes", [["itogo_acc", "ros_acc"], ["ros_acc", "esia_acc"]])
def test_rule_needs_a_total_and_at_least_two_parts(codes):
    """Одна составляющая — не сумма; нет итоговой графы — нечего сверять."""
    current = {("Донецк", c): 10.0 for c in codes}
    assert quality._check_total_column(current, NAMES_RCO) is None
