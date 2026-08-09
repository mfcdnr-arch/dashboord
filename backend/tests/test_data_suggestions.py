"""Предложения метрик из анализа столбцов файла.

Проверка на форме заказчика (МФЦ, внедрение сервиса МАХ): у одного показателя
три столбца-разреза (нарастающим итогом / текущий месяц / за неделю) плюс
отдельный столбец плана. Именно на такой форме легко получить дубли и
бессмысленные пары «неделя против накопительного итога».
"""
from app.modules.metrics.data_suggestions import _build_specs, _is_main_slice, _split_name

DS = {"code": "max_vnedrenie", "periods": 2}
SINGLE_PERIOD = {"code": "max_vnedrenie", "periods": 1}

FIELDS = [
    {"code": "otpr_1", "name": "Количество отправленных уведомлений (из АИС в Notify) · Факт · нарастающим итогом**"},
    {"code": "otpr_3", "name": "Количество отправленных уведомлений (из АИС в Notify) · Факт · за отчетную неделю"},
    {"code": "dost_plan", "name": "Количество успешно доставленных уведомлений (ЛК Notify) · План (до 1 сентября 2026 г.)*"},
    {"code": "dost_2", "name": "Количество успешно доставленных уведомлений (ЛК Notify) · Факт · нарастающим итогом**"},
    {"code": "dost_3", "name": "Количество успешно доставленных уведомлений (ЛК Notify) · Факт · за отчетную неделю"},
    {"code": "dost_4", "name": "Количество успешно доставленных уведомлений (ЛК Notify) · Факт · нарастающим итогом (текущий месяц)"},
]


def _names(specs, kind):
    return [s["name"] for s in specs if s["type"] == kind]


def test_split_name_separates_subject_role_and_slice():
    p = _split_name("Количество обращений в МФЦ · Факт · нарастающим итогом**")
    assert p["role"] == "fact"
    assert p["slice"] == "нарастающим итогом"
    assert p["subject"] == "Количество обращений в МФЦ"


def test_plan_column_is_recognised_by_role():
    p = _split_name("Количество записавшихся (в МАХ) · План (до 1 сентября 2026 г.)*")
    assert p["role"] == "plan"


def test_main_slice_excludes_month_and_week_cuts():
    assert _is_main_slice("нарастающим итогом")
    assert _is_main_slice("")
    assert not _is_main_slice("нарастающим итогом (текущий месяц)")
    assert not _is_main_slice("за отчетную неделю")


def test_plan_fact_suggested_once_against_cumulative_fact():
    specs = _build_specs(DS, FIELDS)
    pf = _names(specs, "plan_fact_pct")
    # ровно одно предложение, хотя «фактов» у показателя три
    assert len(pf) == 1, pf
    formula = next(s["formula"] for s in specs if s["type"] == "plan_fact_pct")
    assert "dost_plan" in formula and "dost_2" in formula
    assert "dost_4" not in formula, "план нельзя сравнивать с месячным срезом"


def test_share_pairs_stay_within_one_slice():
    specs = _build_specs(DS, FIELDS)
    shares = [s for s in specs if s["type"] == "percent_of"]
    assert shares, "доля доставленных от отправленных должна предлагаться"
    for s in shares:
        # обе стороны формулы — столбцы одного разреза
        weekly = ("otpr_3" in s["formula"], "dost_3" in s["formula"])
        assert weekly[0] == weekly[1], f"смешаны разные разрезы: {s['formula']}"


def test_dynamics_only_when_more_than_one_period():
    assert _names(_build_specs(DS, FIELDS), "period_delta")
    assert not _names(_build_specs(SINGLE_PERIOD, FIELDS), "period_delta")


def test_totals_only_for_main_slice():
    totals = _names(_build_specs(DS, FIELDS), "total_sum")
    # два показателя (отправленные и доставленные), а не шесть столбцов
    assert len(totals) == 2, totals


def test_every_suggestion_carries_explanation_and_source():
    for s in _build_specs(DS, FIELDS):
        assert s["why"], "у предложения должно быть пояснение, зачем оно"
        assert s["based_on"] and s["dataset_code"] == "max_vnedrenie"
