"""Готовые рецепты метрик: каждый должен собираться в разбираемую формулу.

Рецепт, который даёт неразбираемое выражение, обнаружился бы только у
пользователя — в момент, когда он уже выбрал столбцы и нажал «Сохранить».
"""
import pytest

from app.modules.metrics.parser import FormulaError, parse
from app.modules.metrics.templates import BY_CODE, TEMPLATES, build_formula, suggested_name


def _values_for(tpl):
    """Правдоподобный выбор пользователя для каждого входа рецепта."""
    out = {}
    for spec in tpl["inputs"]:
        if spec["kind"] == "field":
            out[spec["key"]] = {"dataset_code": "max_vnedrenie", "field": "kolichestvo_obrashcheniy"}
        elif spec["kind"] == "metric":
            out[spec["key"]] = {"metric_code": "dolya_dostavlennyh"}
        else:
            out[spec["key"]] = 95
    return out


@pytest.mark.parametrize("tpl", TEMPLATES, ids=[t["code"] for t in TEMPLATES])
def test_every_template_builds_parseable_formula(tpl):
    formula = build_formula(tpl["code"], _values_for(tpl))
    parse(formula)  # не должно бросать
    assert "{" not in formula, "в формуле остался неподставленный плейсхолдер"


def test_templates_have_unique_codes_and_required_fields():
    assert len(BY_CODE) == len(TEMPLATES), "коды рецептов должны быть уникальны"
    for t in TEMPLATES:
        assert t["name"] and t["group"] and t["description"] and t["example"]
        assert t["inputs"], "у рецепта должен быть хотя бы один вход"
        for spec in t["inputs"]:
            assert "{" + spec["key"] + "}" in t["formula"], f"вход {spec['key']} не используется в формуле"


def test_missing_field_choice_is_rejected():
    with pytest.raises(FormulaError, match="выберите датасет и столбец"):
        build_formula("percent_of", {"part": {"dataset_code": "ds"}, "base": None})


def test_division_by_zero_is_rejected():
    with pytest.raises(FormulaError, match="на ноль делить нельзя"):
        build_formula("per_unit", {"a": {"dataset_code": "ds", "field": "f"}, "n": 0})


def test_apostrophe_in_field_name_does_not_break_formula():
    # Апостроф — кавычка строкового литерала DSL; если его не убрать, формула
    # развалится на разборе и пользователь увидит невнятную ошибку.
    formula = build_formula("total_sum", {"a": {"dataset_code": "ds'x", "field": "f'y"}})
    parse(formula)


def test_unknown_template_is_rejected():
    with pytest.raises(FormulaError, match="Неизвестный рецепт"):
        build_formula("нет_такого", {})


def test_suggested_name_uses_column_labels():
    name = suggested_name("percent_of", {"part": "Доставлено", "base": "Отправлено"})
    assert "Доставлено" in name and "Отправлено" in name
