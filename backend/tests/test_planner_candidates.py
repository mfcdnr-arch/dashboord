"""Планировщик виджетов: ВСЕ кандидаты с «рекомендую / не рекомендую, потому что…».

Решения заказчика 23.09.2026, которые здесь держатся:

* лимит считается в КАРТОЧКАХ, а не в графах: рекомендуется до 35, остальные
  остаются в списке с причиной и добавляются галочкой;
* графы, отмеченные человеком вручную, не урезаются — вместо запрета
  предупреждение;
* большая форма с подтверждёнными ступенями раскладывается по страницам
  ведомств, а не одной стеной карточек;
* «не рекомендую, потому что…» живёт в самом планировщике, поэтому предложение
  и «Собрать дашборд» видят одно и то же;
* что будет СОЗДАНО — решает признак `build`, и `plan_auto_build` обязан
  создавать ровно это (одна функция на предпросмотр и сборку).

Функции чистые — БД не нужна.
"""
from collections import Counter

from app.modules.dashboards import _suggest as sg


def _ds(fields, rows=62, periods=5, volumes=None, levels=None, sums=None, code="t"):
    return [{"code": code, "name": "Форма РЦО", "periods": periods, "releases": periods,
             "rows": rows, "fields": fields,
             "period_dates": [f"2026-09-{i + 1:02d}" for i in range(periods)],
             "sums": sums or {}, "volumes": volumes or {}, "levels": levels}]


def _wide(n=60):
    """Широкая форма: n услуг по две меры, объём убывает с номером услуги."""
    fields, volumes = [], {}
    for i in range(n):
        for tail, suf in (("Принято, ед.", "p"), ("Выдано, ед.", "v")):
            code = f"s{i}{suf}"
            fields.append({"code": code, "name": f"Услуга {i} · {tail}"})
            volumes[code] = float(1000 - i)
    return fields, volumes


def _cards(res):
    return [c for c in res["candidates"] if c["cards"]]


def test_card_limit_counts_cards_not_fields():
    """🔴 Лимит — в карточках: 120 граф дают 60 карточек, рекомендуется 35.

    До 24.09 потолок стоял в ГРАФАХ (24), и у РЦО он давал всего 8 карточек:
    графы одного предмета собираются в одну карточку.
    """
    fields, volumes = _wide(60)
    res = sg.plan_candidates(_ds(fields, volumes=volumes))
    cards = _cards(res)
    assert len(cards) == 60 and all(c["widget_type"] == "kpi_group" for c in cards)
    assert {k: res["cards"][k] for k in ("recommended", "total", "limit", "manual")} == {
        "recommended": sg.MAX_CARDS, "total": 60, "limit": sg.MAX_CARDS, "manual": False}
    rec = [c for c in cards if c["recommended"]]
    assert len(rec) == sg.MAX_CARDS
    # Рекомендуются самые нагруженные, а не первые по порядку файла.
    assert {c["name"] for c in rec} == {f"Услуга {i}" for i in range(sg.MAX_CARDS)}
    rest = [c for c in cards if not c["recommended"]]
    assert all(not c["build"] and f"Сверх {sg.MAX_CARDS}" in c["reason"] for c in rest)
    assert any("можно сделать 60" in n for n in res["notes"]), "урезание называется словами"


def test_busiest_cards_win_even_when_they_are_last_in_the_file():
    """🔴 На форме из сотен граф «первые N» — это лотерея (РЦО, 02.09).

    Нагруженные графы лежат в КОНЦЕ списка — ровно как в форме заказчика:
    рекомендованы должны быть они, а не редкие услуги из начала файла.
    """
    fields, _ = _wide(60)
    volumes = {f["code"]: 0.0 for f in fields}
    for f in fields[-10:]:
        volumes[f["code"]] = 500.0
    res = sg.plan_candidates(_ds(fields, volumes=volumes))
    rec = {c["name"] for c in _cards(res) if c["recommended"]}
    assert {f"Услуга {i}" for i in range(55, 60)} <= rec
    zero = next(c for c in _cards(res) if c["name"] == "Услуга 0")
    assert not zero["recommended"] and "ни одного ненулевого" in zero["reason"]


def test_zero_cards_stay_on_a_form_that_fits():
    """На форме, которая помещается целиком, карточка с нулём — тоже сведения.

    «Отказов 0» — ответ, а не пустота; правило 11.08 «сколько показателей в
    разметке, столько карточек» действует, пока резать не приходится.
    """
    fields, _ = _wide(5)
    volumes = {f["code"]: (0.0 if f["code"].startswith("s0") else 10.0) for f in fields}
    res = sg.plan_candidates(_ds(fields, volumes=volumes))
    assert all(c["recommended"] for c in _cards(res))


def test_manual_selection_is_not_truncated():
    """Графы, отмеченные человеком, не урезаются — вместо запрета предупреждение."""
    fields, volumes = _wide(60)
    picked = [f["code"] for f in fields[:80]]          # 40 услуг из 60
    res = sg.plan_candidates(_ds(fields, volumes=volumes), {"t": {"fields": picked, "manual": True}})
    cards = _cards(res)
    assert len(cards) == 40 and all(c["recommended"] and c["build"] for c in cards)
    assert res["cards"]["manual"] is True
    assert any("больше 35" in n for n in res["notes"])


def test_unchecking_a_few_fields_is_not_manual_selection():
    """🔴 Снять лишнее — это исключение, а не ручной выбор (находка 24.09).

    Первая редакция считала ручным любой список короче полного: снятая одна
    графа из 331 у РЦО отменяла лимит, и вместо 35 карточек рекомендовалось
    146. Ручной выбор теперь — явный признак `manual` (мастер ставит его,
    когда человек нажал «снять» и отмечает графы сам).
    """
    fields, volumes = _wide(60)
    for picked in ([f["code"] for f in fields], [f["code"] for f in fields[2:]]):
        res = sg.plan_candidates(_ds(fields, volumes=volumes), {"t": {"fields": picked}})
        assert res["cards"]["manual"] is False and res["cards"]["recommended"] == sg.MAX_CARDS


def test_include_and_exclude_decide_what_is_built():
    """Галочка человека сильнее рекомендации — в обе стороны."""
    fields, volumes = _wide(60)
    base = sg.plan_candidates(_ds(fields, volumes=volumes))["candidates"]
    off = next(c for c in base if c["cards"] and not c["recommended"])
    on = next(c for c in base if c["cards"] and c["recommended"])
    sel = {"t": {"include": [off["key"]], "exclude": [on["key"]]}}
    got = {c["key"]: c for c in sg.plan_candidates(_ds(fields, volumes=volumes), sel)["candidates"]}
    assert got[off["key"]]["build"] and not got[off["key"]]["recommended"]
    assert not got[on["key"]]["build"] and got[on["key"]]["recommended"]
    built = sg.plan_auto_build(_ds(fields, volumes=volumes), sel)
    assert len(built) == sum(1 for c in got.values() if c["build"])


def test_keys_are_unique_and_stable():
    """По ключу запоминается галочка: он обязан быть уникальным и не плясать."""
    fields, volumes = _wide(60)
    a = [c["key"] for c in sg.plan_candidates(_ds(fields, volumes=volumes))["candidates"]]
    b = [c["key"] for c in sg.plan_candidates(_ds(fields, volumes=volumes))["candidates"]]
    assert a == b
    assert len(a) == len(set(a)), [k for k, n in Counter(a).items() if n > 1]


def test_preview_builds_exactly_what_the_candidates_promise():
    """Одна функция на предпросмотр и сборку: обещанное = созданному."""
    fields, volumes = _wide(40)
    res = sg.plan_candidates(_ds(fields, volumes=volumes))
    built = sg.plan_auto_build(_ds(fields, volumes=volumes))
    promised = [(c["page"], c["name"], c["widget_type"]) for c in res["candidates"] if c["build"]]
    assert [(s["page"], s["name"], s["widget_type"]) for s in built] == promised


def test_layout_rows_do_not_overlap():
    """🔴 Высота ряда — по самой высокой карточке ряда (РЦО, 24.09: налезали)."""
    fields, volumes = _wide(40)
    fields.append({"code": "tot", "name": "ИТОГО · Принято, ед."})
    volumes["tot"] = 99999.0
    specs = sg.plan_auto_build(_ds(fields, volumes=volumes))
    by_page: dict = {}
    for s in specs:
        by_page.setdefault(s["page"], []).append(s)
    for page, items in by_page.items():
        for i, a in enumerate(items):
            assert a["position_x"] + a["width"] <= 12
            for b in items[i + 1:]:
                apart = (a["position_x"] + a["width"] <= b["position_x"]
                         or b["position_x"] + b["width"] <= a["position_x"]
                         or a["position_y"] + a["height"] <= b["position_y"]
                         or b["position_y"] + b["height"] <= a["position_y"])
                assert apart, f"{page}: «{a['name']}» и «{b['name']}» налезают"


def test_alerts_off_means_no_thresholds_anywhere():
    """🔴 Галочка «подсвечивать невыполнение» снята — порогов нет ни у кого.

    До 24.09 её слушалась только полоса «план-факт»: светофору, полосам и
    термометру пороги ставились всё равно.
    """
    fields = [
        {"code": "p1", "name": "Записались · План (до 1 сентября 2026 г.)"},
        {"code": "f1", "name": "Записались · Факт · нарастающим итогом"},
        {"code": "p2", "name": "Доставлено · План (до 1 сентября 2026 г.)"},
        {"code": "f2", "name": "Доставлено · Факт · нарастающим итогом"},
    ]
    volumes = {c["code"]: 10.0 for c in fields}
    for alerts, check in ((False, lambda a: a == []), (True, lambda a: bool(a))):
        cands = sg.plan_candidates(_ds(fields, rows=12, volumes=volumes), alerts=alerts)["candidates"]
        kinds = {c["widget_type"]: c for c in cands}
        for kind in ("status_grid", "bullet", "thermometer"):
            assert kind in kinds, kind
            assert check(kinds[kind]["config"].get("alerts")), (alerts, kind)


def test_status_grid_without_plan_is_offered_but_not_built():
    """Находка 23.09: светофор без плана на РЦО — серые плитки, повтор рейтинга."""
    fields = [{"code": "a", "name": "ИТОГО · Выдано, ед."}]
    cands = sg.plan_candidates(_ds(fields, volumes={"a": 5.0}))["candidates"]
    grid = next(c for c in cands if c["widget_type"] == "status_grid")
    assert not grid["build"] and "плана" in grid["reason"] and "рейтинг" in grid["reason"]


def test_colon_forms_group_measures_and_compare_one_measure():
    """🔴 Форма «Статистики услуг» («Услуга 1: Принято») разбором имён не понималась.

    14 граф МВД давали 14 отдельных карточек вместо семи «Услуга N»; а
    «Сравнение» складывало на одном графике принятое с выданным.
    """
    fields, volumes = [], {}
    for i in range(1, 8):
        for m in ("Принято", "Выдано"):
            code = f"u{i}{m[0]}"
            fields.append({"code": code, "name": f"Услуга {i}: {m}"})
            volumes[code] = float(100 - i)
    res = sg.plan_candidates(_ds(fields, volumes=volumes))
    cards = _cards(res)
    assert len(cards) == 7 and all(c["widget_type"] == "kpi_group" for c in cards)
    cmp_ = next(c for c in res["candidates"] if c["widget_type"] == "compare")
    names = {f["name"] for f in fields if f["code"] in cmp_["config"]["value_fields"]}
    assert {n.split(":")[1].strip() for n in names} == {"Принято"}
    assert cmp_["name"].endswith("Принято")


def test_compare_leaves_out_totals_and_mixed_measures():
    """Свод содержит части, а «Принято» и «Выдано» — стадии одного обращения."""
    fields = [{"code": "tot", "name": "ИТОГО · Принято, ед."}]
    volumes = {"tot": 1000.0}
    for i in range(3):
        for m, s in (("Принято, ед.", "p"), ("Выдано, ед.", "v")):
            fields.append({"code": f"d{i}{s}", "name": f"Ведомство {i} · {m}"})
            volumes[f"d{i}{s}"] = 10.0
    cmp_ = next(c for c in sg.plan_candidates(_ds(fields, volumes=volumes))["candidates"]
                if c["widget_type"] == "compare")
    assert "tot" not in cmp_["config"]["value_fields"]
    assert len({f[-1] for f in cmp_["config"]["value_fields"]}) == 1, "одна мера"


def test_confirmed_levels_split_cards_into_department_pages():
    """Большая форма со ступенями — по страницам ведомств (решение 23.09).

    Своды и крупные ведомства без услуг остаются на «Обзоре»; ведомство с
    двумя и больше карточками получает свою страницу; на ней имя ведомства в
    карточке не повторяется.
    """
    fields = [{"code": "it_p", "name": "ИТОГО · Принято, ед."},
              {"code": "it_v", "name": "ИТОГО · Выдано, ед."},
              {"code": "esia", "name": "ЕСИА · Принято, ед."},
              {"code": "rr5", "name": "Росреестр · Услуга 5 · Принято, ед."}]
    volumes = {"it_p": 5000.0, "it_v": 4000.0, "esia": 900.0, "rr5": 30.0}
    for d in ("Росреестр", "МВД", "СФР"):
        for s in range(1, 5):
            for m, mm in (("Принято, ед.", "p"), ("Выдано, ед.", "v")):
                code = f"{d[:2]}{s}{mm}"
                fields.append({"code": code, "name": f"{d} · Услуга {s} · {m}"})
                volumes[code] = 100.0 / s
    levels = {"levels": [{"name": "Ведомство"}, {"name": "Услуга"}]}
    res = sg.plan_candidates(_ds(fields, volumes=volumes, levels=levels))
    pages = {c["name"]: c["page"] for c in _cards(res)}
    assert pages["ИТОГО"] == sg.PAGE_OVERVIEW
    assert pages["ЕСИА · Принято, ед."] == sg.PAGE_OVERVIEW
    assert pages["Услуга 5 · Принято, ед."] == "Росреестр", "имя ведомства снято со страницы ведомства"
    built_pages = {c["page"] for c in res["candidates"] if c["build"]}
    assert {"Росреестр", "МВД", "СФР"} <= built_pages
    assert any("разложены по страницам ведомств" in n for n in res["notes"])

    # Без подтверждённых ступеней — никакой раскладки: лучше одна страница,
    # чем страницы по неверно угаданной иерархии.
    flat = sg.plan_candidates(_ds(fields, volumes=volumes))
    assert {c["page"] for c in _cards(flat)} == {sg.PAGE_OVERVIEW}


def test_extra_dynamics_are_offered_with_a_reason():
    """Графиков динамики больше, чем различимо на странице, — лишние не молчат."""
    fields, volumes = _wide(12)
    fields = [{**f, "name": f["name"] + " · за отчетную неделю"} for f in fields]
    res = sg.plan_candidates(_ds(fields, rows=1, volumes=volumes))
    dyn = [c for c in res["candidates"] if c["widget_type"] == "dynamics"]
    assert any(c["recommended"] for c in dyn)
    extra = [c for c in dyn if not c["recommended"]]
    assert extra and all(c["reason"] and not c["build"] for c in extra)


def test_bar_on_a_single_row_is_not_recommended():
    """Строка в форме одна — график из одного столбика ничего не добавляет."""
    fields = [{"code": "a", "name": "Обращения · Факт · нарастающим итогом"}]
    bar = next(c for c in sg.plan_candidates(_ds(fields, rows=1, volumes={"a": 1.0}))["candidates"]
               if c["widget_type"] == "bar")
    assert not bar["build"] and "одного столбика" in bar["reason"]


def test_pinned_period_applies_to_every_candidate():
    """Дашборд по конкретному файлу: дата закрепляется у ВСЕХ видов разом."""
    fields, volumes = _wide(3)
    cands = sg.plan_candidates(_ds(fields, volumes=volumes), pin_period="2026-09-03")["candidates"]
    assert cands and all(c["config"].get("period") == "2026-09-03" for c in cands)


def test_marks_survive_the_next_file():
    """🔴 Ключ не включает дату закрепления: через неделю, по следующему файлу,
    снятые и добавленные виджеты остаются снятыми и добавленными (ревью этапа 2)."""
    fields, volumes = _wide(40)
    a = [c["key"] for c in sg.plan_candidates(_ds(fields, volumes=volumes), pin_period="2026-09-04")["candidates"]]
    b = [c["key"] for c in sg.plan_candidates(_ds(fields, volumes=volumes), pin_period="2026-09-11")["candidates"]]
    assert a == b


def test_one_per_dataset_kinds_keep_their_key_when_fields_change():
    """🔴 Снятое «Сравнение» не возвращается после правки состава граф."""
    fields, volumes = _wide(40)
    base = {c["widget_type"]: c for c in sg.plan_candidates(_ds(fields, volumes=volumes))["candidates"]}
    cmp_key = base["compare"]["key"]
    fewer = [f["code"] for f in fields if f["code"] != "s0p"]
    sel = {"t": {"fields": fewer, "exclude": [cmp_key]}}
    again = {c["widget_type"]: c for c in sg.plan_candidates(_ds(fields, volumes=volumes), sel)["candidates"]}
    assert again["compare"]["key"] == cmp_key and not again["compare"]["build"]


def test_card_limit_is_per_form():
    """Лимит карточек действует на КАЖДУЮ форму: две формы по 35 — это не превышение."""
    fields, volumes = _wide(60)
    two = _ds(fields, volumes=volumes, code="a") + _ds(fields, volumes=volumes, code="b")
    stats = sg.plan_candidates(two)["cards"]
    assert stats["recommended"] == 2 * sg.MAX_CARDS
    assert stats["by_dataset"]["a"]["recommended"] == sg.MAX_CARDS
    assert stats["by_dataset"]["b"]["recommended"] == sg.MAX_CARDS


def test_pie_reason_matches_what_the_pie_does():
    """На 8 строках круговая рисует 8 секторов без «Прочих» — причина не обещает их."""
    from app.modules.dashboards._widgetcalc import MAX_PIE_SLICES

    f = [{"code": "a", "name": "Обращения · Факт · нарастающим итогом"}]
    reason = lambda rows: next(c for c in sg.plan_candidates(_ds(f, rows=rows, volumes={"a": 1.0}))["candidates"]  # noqa: E731
                               if c["widget_type"] == "pie")["reason"]
    assert "Прочие" not in reason(MAX_PIE_SLICES)
    assert "Прочие" in reason(MAX_PIE_SLICES + 1)


def test_extra_trend_is_not_said_to_be_in_the_matrix_when_it_is_not():
    """Матрица по строкам берёт ОДНУ графу — про остальные «уже показано» неправда."""
    fields, volumes = _wide(12)
    fields = [{**f, "name": f["name"] + " · за отчетную неделю"} for f in fields]
    cands = sg.plan_candidates(_ds(fields, rows=62, volumes=volumes))["candidates"]
    matrix = next(c for c in cands if c["widget_type"] == "matrix")
    in_matrix = set(matrix["config"].get("value_fields") or [matrix["config"].get("value_field")])
    for c in cands:
        if c["widget_type"] == "dynamics" and not c["recommended"]:
            said = "уже показывает матрица" in c["reason"]
            assert said == (c["config"]["value_field"] in in_matrix), c["reason"]


def test_saved_marks_are_pruned_to_known_candidates():
    """Сервер сам чистит сохранённые отметки: мастер их больше не отсекает."""
    fields, volumes = _wide(40)
    cands = sg.plan_candidates(_ds(fields, volumes=volumes))["candidates"]
    k = cands[0]["key"]
    sel = {"t": {"include": [k, "t:kpi:nope"], "exclude": [k, "t:bar:gone"]}}
    pruned = sg._prune_marks(sel, cands)["t"]
    assert pruned["exclude"] == [k] and pruned["include"] == [], "«добавлен и снят» сводится к «снят»"
