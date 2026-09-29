"""Пояснение виджета частями: одно и то же в предложении и в ⓘ.

Решение заказчика 23.09.2026: «текст из предложения остаётся у созданного
виджета в ⓘ, и пользователь дашборда видит то же, что видел модератор при
выборе». Поэтому части пояснения строит одна чистая функция
`widget_sections`, а здесь держится, что:

* у каждого кандидата, которого предлагает планировщик, пояснение есть —
  предложение без объяснения «что покажет» заказчик прямо отверг;
* имена видов совпадают с галереей виджетов на экране;
* имена граф грузятся у всех видов, а не только у видов с одной графой.
"""
import re
from pathlib import Path

from app.modules.dashboards import _explain as ex
from app.modules.dashboards import _suggest as sg

FRONT = Path("/frontend/src")
if not FRONT.exists():  # локальный прогон вне контейнера
    FRONT = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _ctx(fields, code="t", form="РЦО: ежедневный отчёт"):
    return {"metrics": {}, "forms": {code: form},
            "fields": {(code, f["code"]): {"name": f["name"], "description": None, "unit": None,
                                           "dataset_code": code, "dataset_name": form}
                       for f in fields}}


def _sec(widget_type, cfg, fields):
    return ex.widget_sections({"widget_type": widget_type, "config": {"dataset_code": "t", **cfg}},
                              _ctx(fields))


def test_type_labels_match_the_gallery():
    """Чип вида в предложении называет вид теми же словами, что галерея виджетов."""
    src = (FRONT / "components" / "dashboards" / "WidgetPicker.tsx").read_text(encoding="utf-8")
    gallery = dict(re.findall(r"\{ v: '(\w+)', t: '([^']+)'", src))
    assert len(gallery) >= 26, "галерея не разобралась — проверка ослепла бы молча"
    assert gallery == ex.WIDGET_TYPE_RU


def test_field_codes_cover_every_kind_of_config():
    """🔴 Имена граф грузились только у видов с одной графой (находка 24.09).

    Одинокое «Сравнение» говорило «Графы формы: …» пустым списком.
    """
    assert ex._field_codes({"value_fields": ["a", "b"]}) == ["a", "b"]
    assert ex._field_codes({"plan_field": "p", "fact_field": "f"}) == ["p", "f"]
    assert ex._field_codes({"pairs": [{"plan_field": "p1", "fact_field": "f1"}]}) == ["p1", "f1"]


def test_every_planned_candidate_is_explained():
    """Ни один кандидат планировщика не остаётся без «что покажет»."""
    fields = [
        {"code": "tot", "name": "ИТОГО · Принято, ед."},
        {"code": "p1", "name": "Записались · План (до 1 сентября 2026 г.)"},
        {"code": "f1", "name": "Записались · Факт · нарастающим итогом"},
        {"code": "p2", "name": "Доставлено · План (до 1 сентября 2026 г.)"},
        {"code": "f2", "name": "Доставлено · Факт · нарастающим итогом"},
        {"code": "w1", "name": "Записались · Факт · за отчетную неделю"},
        {"code": "sh", "name": "Доля доставленных, %"},
    ]
    for i in range(6):
        fields.append({"code": f"s{i}", "name": f"Ведомство {i} · Принято, ед."})
    ds = [{"code": "t", "name": "РЦО", "periods": 20, "releases": 20, "rows": 62,
           "fields": fields, "period_dates": ["2025-09-01", "2026-09-01"],
           "sums": {f["code"]: 10.0 for f in fields},
           "volumes": {f["code"]: 10.0 for f in fields}, "levels": None}]
    cands = sg.plan_candidates(ds)["candidates"]
    kinds = {c["widget_type"] for c in cands}
    assert {"kpi_group", "gauge", "bullet", "thermometer", "status_grid", "ranked", "heatmap",
            "waterfall", "matrix", "dynamics", "bar", "table", "compare", "yoy"} <= kinds
    ctx = _ctx(fields)
    for c in cands:
        sec = ex.widget_sections({"widget_type": c["widget_type"], "config": c["config"]}, ctx)
        assert sec.get("what"), f"{c['widget_type']} «{c['name']}» без пояснения"
        assert sec.get("answers"), f"{c['widget_type']} «{c['name']}» не говорит, на что отвечает"


def test_waterfall_explains_its_own_fold():
    """Водопад по периодам: у накопительного итога ступени — приросты, у потока — значения."""
    cum = [{"code": "c", "name": "Обращения · Факт · нарастающим итогом"}]
    flow = [{"code": "w", "name": "Обращения · Факт · за отчетную неделю"}]
    assert "прирост" in _sec("waterfall", {"value_field": "c", "by": "periods"}, cum)["how"]
    assert "поток" in _sec("waterfall", {"value_field": "w", "by": "periods"}, flow)["how"]


def test_status_grid_says_when_colour_means_nothing():
    """Без плана светофор так и говорит: плитки одного цвета."""
    f = [{"code": "a", "name": "ИТОГО · Выдано, ед."}, {"code": "p", "name": "ИТОГО · План"}]
    bare = _sec("status_grid", {"value_field": "a"}, f)
    assert "одного цвета" in bare["caveats"]
    planned = _sec("status_grid", {"value_field": "a", "plan_field": "p",
                                   "alerts": [{"op": "lt", "value": 90, "level": "red"}]}, f)
    assert "выполнению плана" in planned["what"] and "одного цвета" not in planned.get("caveats", "")
    # 🔴 Ревью этапа 2: галочка «подсвечивать невыполнение» снята — alerts=[],
    # плитки бесцветные даже при плане, и ⓘ не должен обещать цвет по плану.
    off = _sec("status_grid", {"value_field": "a", "plan_field": "p", "alerts": []}, f)
    assert "выполнению плана" not in off["what"] and "Пороги сняты" in off["caveats"]


def test_thermometer_names_the_deadline_in_words():
    """ISO-дата в подсказке читается как код — срок пишется словами."""
    f = [{"code": "p", "name": "План"}, {"code": "f", "name": "Факт"}]
    sec = _sec("thermometer", {"plan_field": "p", "fact_field": "f", "deadline": "2026-09-01"}, f)
    assert "1 сентября 2026 г." in sec["what"]


def test_ranked_by_measure_is_named_as_a_measure():
    """Рейтинг по мере — свод всех граф с этим хвостом, а не одна графа."""
    sec = _sec("ranked", {"measure": "Принято, ед."}, [])
    assert "Мера «Принято, ед.»" in sec["what"]


def test_pinned_period_is_always_mentioned():
    """Срез за дату: без оговорки человек ждёт, что виджет обновится сам."""
    f = [{"code": "a", "name": "ИТОГО · Выдано, ед."}]
    for kind in ("kpi", "dynamics", "bar", "table", "ranked"):
        sec = _sec(kind, {"value_field": "a", "period": "2026-07-22"}, f)
        assert "22 июля 2026 г." in sec.get("caveats", ""), kind


def test_text_order_and_clip():
    """Порядок частей в ⓘ один для всех видов, длина ограничена."""
    text = ex.sections_text({"caveats": "В.", "what": "А.", "answers": "Б."})
    assert text == "А. Отвечает: Б. Учтите: В."
    long = ex._clip("слово " * 400)
    assert len(long) <= ex.MAX_EXPLAIN and long.endswith("…")


def test_pinned_series_say_the_series_stops():
    """У видов-рядов закрепление обрывает ряд — так и сказано (ревью этапа 2)."""
    f = [{"code": "a", "name": "ИТОГО · Выдано, ед."}]
    dyn = _sec("dynamics", {"value_field": "a", "period": "2026-07-22"}, f)
    assert "ряд обрывается на этой дате" in dyn["caveats"]
    kpi = _sec("kpi", {"value_field": "a", "period": "2026-07-22"}, f)
    assert "ряд обрывается" not in kpi["caveats"]
    table = _sec("table", {"period": "2026-07-22"}, f)
    assert "отчёта за 22 июля 2026 г." in table["what"], "не «последнего отчёта» на срезе"


def test_ranked_and_pie_do_not_promise_what_is_not_drawn():
    """Рейтинг сворачивает середину только на длинном списке, круговая — после порога."""
    from app.modules.dashboards._widgetcalc import MAX_PIE_SLICES

    assert "Когда строк больше" in _sec("ranked", {"value_field": "a"}, [])["caveats"]
    assert f"больше {MAX_PIE_SLICES}" in _sec("pie", {"value_field": "a"}, [])["caveats"]
