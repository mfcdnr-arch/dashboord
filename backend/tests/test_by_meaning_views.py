"""Выбор вида виджета ПО СМЫСЛУ ДАННЫХ (авто-сборка).

Главное, что проверяем, — не «сработало», а «промолчало там, где данных не
хватает». Виджет, поставленный на всякий случай, показывает правдоподобную
неправду, и это дороже его отсутствия.
"""
from app.modules.dashboards._suggest import by_meaning_specs


def _f(code, name):
    return {"code": code, "name": name}


# Настоящие имена столбцов формы заказчика «Внедрение сервиса МАХ».
MAX_FIELDS = [
    _f("otpr", "Количество отправленных уведомлений о готовности · Факт · нарастающим итогом"),
    _f("dost", "Количество успешно доставленных уведомлений · Факт · нарастающим итогом"),
    _f("obr", "Количество обращений за результатом оказания услуг в МФЦ · Факт · нарастающим итогом"),
    _f("zap", "Количество пользователей, записавшихся на посещение МФЦ · Факт · нарастающим итогом"),
]
# Настоящие суммы за 19.08.2026: отправлено 2,5 млн, обращений 1,0 млн,
# доставлено 943 тыс., записались 275 тыс.
MAX_SUMS = {"otpr": 2537581.0, "obr": 1000864.0, "dost": 943442.0, "zap": 275694.0}


def kinds(*a, **kw):
    return [s["kind"] for s in by_meaning_specs(*a, **kw)]


def test_funnel_not_built_when_stages_do_not_nest():
    """🔴 Реальный случай заказчика: по словарю цепочка складывается, а по числам —

    нет. «Обращения» не являются частью «отправленных уведомлений»: это разные
    сущности, просто одно число меньше другого. Такая воронка выглядит
    убедительно и врёт, поэтому строиться не должна.
    """
    # Порядок ступеней словаря: отправлено → доставлено → обращения → записались.
    # По числам доставлено (943k) < обращения (1000k) — вложенность нарушена.
    assert "funnel" not in kinds(MAX_FIELDS, rows=1, periods=4, values=MAX_SUMS)


def test_funnel_needs_values_at_all():
    """Без значений воронка не строится вовсе: правило закрыто по умолчанию.

    Одного словаря мало — именно он и дал бы ложную цепочку выше.
    """
    assert "funnel" not in kinds(MAX_FIELDS, rows=1, periods=4, values=None)


def test_funnel_built_when_stages_really_nest():
    """А когда ступени действительно вложены — воронка нужна и строится."""
    sums = {"otpr": 1000.0, "dost": 800.0, "obr": 500.0, "zap": 200.0}
    got = by_meaning_specs(MAX_FIELDS, rows=1, periods=4, values=sums)
    funnel = next((s for s in got if s["kind"] == "funnel"), None)
    assert funnel is not None
    # Ступени идут по убыванию — иначе воронка нарисуется расширяющейся.
    seq = [sums[f["code"]] for f in funnel["fields"]]
    assert seq == sorted(seq, reverse=True)


def test_two_stages_are_not_a_funnel():
    """Два этапа — это обычный процент, и «Доля доставленных» отвечает точнее."""
    two = MAX_FIELDS[:2]
    assert "funnel" not in kinds(two, rows=1, periods=4,
                                 values={"otpr": 1000.0, "dost": 800.0})


def test_status_grid_and_heatmap_need_rows():
    """Светофор и тепловая карта — про строки. На одной строке они бессмысленны."""
    one_row = kinds(MAX_FIELDS, rows=1, periods=4, values=MAX_SUMS)
    assert "status_grid" not in one_row and "heatmap" not in one_row

    many = kinds(MAX_FIELDS, rows=62, periods=4, values=MAX_SUMS)
    assert "status_grid" in many and "heatmap" in many


def test_pie_only_for_a_few_rows():
    """Круговая честна на немногих долях: на 62 секторах подписи слипаются."""
    assert "pie" in kinds(MAX_FIELDS, rows=5, periods=1, values=MAX_SUMS)
    assert "pie" not in kinds(MAX_FIELDS, rows=62, periods=1, values=MAX_SUMS)
    assert "pie" not in kinds(MAX_FIELDS, rows=2, periods=1, values=MAX_SUMS)


def test_waterfall_needs_cumulative_field_and_a_series():
    """Водопад показывает вклад периодов: нужен накопительный итог и ряд точек."""
    assert "waterfall" in kinds(MAX_FIELDS, rows=1, periods=4, values=MAX_SUMS)
    # Две точки — это ещё не ряд.
    assert "waterfall" not in kinds(MAX_FIELDS, rows=1, periods=2, values=MAX_SUMS)
    # Нет накопительного показателя — нечего раскладывать по периодам.
    weekly = [_f("w", "Количество обращений · Факт · за отчетную неделю")]
    assert "waterfall" not in kinds(weekly, rows=1, periods=4, values={"w": 10.0})


def test_yoy_only_across_calendar_years():
    """«Год к году» без второго года сравнивал бы год сам с собой."""
    same = kinds(MAX_FIELDS, rows=1, periods=4, values=MAX_SUMS,
                 first_period="2026-04-01", last_period="2026-08-19")
    assert "yoy" not in same

    across = kinds(MAX_FIELDS, rows=1, periods=4, values=MAX_SUMS,
                   first_period="2025-09-01", last_period="2026-08-19")
    assert "yoy" in across


def test_plan_and_share_columns_are_not_taken_as_facts():
    """Плановые и процентные графы — не предмет для этих видов.

    План — это норма, а не значение; долю нельзя складывать по строкам, и
    светофор по ней показал бы бессмыслицу.
    """
    fields = [
        _f("plan", "Количество записавшихся · План (до 1 сентября 2026 г.)"),
        _f("share", "Доля доставленных, %"),
        _f("fact", "Количество записавшихся · Факт · нарастающим итогом"),
    ]
    got = by_meaning_specs(fields, rows=20, periods=3, values={"plan": 1.0, "share": 2.0, "fact": 3.0})
    used = {f["code"] for s in got for f in s["fields"]}
    assert "plan" not in used and "share" not in used
    assert "fact" in used
