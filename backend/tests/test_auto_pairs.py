"""Связки «часть → целое», найденные ПО ДАННЫМ, а не по словарю слов.

Заказчик: «сделай так, чтобы система сама определяла в формах другие устойчивые
связки, которых ещё нет, и после добавления проверяла, что всё работает».
Словарь знает только вписанные в него пары слов; здесь вывод делается из чисел.
"""
from app.modules.metrics.data_suggestions import _build_specs, _detect_part_of_whole, _split_name

DS = {"code": "ds", "periods": 2}

# Пара, которой НЕТ в словаре воронок: «выдано справок» и «принято заявлений».
FIELDS = [
    {"code": "prinyato", "name": "Принято заявлений · Факт · нарастающим итогом"},
    {"code": "vydano", "name": "Выдано справок · Факт · нарастающим итогом"},
]
PARSED = [{**f, **_split_name(f["name"])} for f in FIELDS]

# Выдано всегда меньше принятого — устойчивая вложенность в каждой точке.
VALUES = {
    "prinyato": {("p1", "р-н A"): 1000.0, ("p1", "р-н B"): 800.0, ("p2", "р-н A"): 1200.0, ("p2", "р-н B"): 900.0},
    "vydano": {("p1", "р-н A"): 700.0, ("p1", "р-н B"): 560.0, ("p2", "р-н A"): 850.0, ("p2", "р-н B"): 620.0},
}


def test_finds_pair_absent_from_dictionary():
    pairs = _detect_part_of_whole(VALUES, PARSED)
    assert ("vydano", "prinyato") in [(a, b) for a, b, _ in pairs]
    avg = next(r for a, b, r in pairs if a == "vydano" and b == "prinyato")
    assert 65 < avg < 75, avg  # средняя доля ~69 %


def test_reverse_direction_is_not_offered():
    # «принято от выданного» смысла не имеет: часть не может превышать целое.
    pairs = [(a, b) for a, b, _ in _detect_part_of_whole(VALUES, PARSED)]
    assert ("prinyato", "vydano") not in pairs


def test_single_crossing_point_breaks_the_pair():
    # Достаточно одной точки, где «часть» больше «целого», — связки нет.
    bad = {**VALUES, "vydano": {**VALUES["vydano"], ("p2", "р-н B"): 5000.0}}
    assert _detect_part_of_whole(bad, PARSED) == []


def test_too_few_points_are_not_enough():
    # Две точки могут совпасть случайно — нужен порог.
    few = {c: dict(list(v.items())[:2]) for c, v in VALUES.items()}
    assert _detect_part_of_whole(few, PARSED) == []


def test_near_identical_columns_are_not_a_pair():
    # Столбцы, отличающиеся на доли процента, — это дубль, а не «часть от целого».
    same = {"prinyato": VALUES["prinyato"],
            "vydano": {k: v * 0.999 for k, v in VALUES["prinyato"].items()}}
    assert _detect_part_of_whole(same, PARSED) == []


def test_plan_column_is_never_used_as_whole():
    fields = FIELDS + [{"code": "plan", "name": "Принято заявлений · План (до 1 сентября)"}]
    parsed = [{**f, **_split_name(f["name"])} for f in fields]
    values = {**VALUES, "plan": {k: v * 2 for k, v in VALUES["prinyato"].items()}}
    pairs = [(a, b) for a, b, _ in _detect_part_of_whole(values, parsed)]
    assert all("plan" not in p for p in pairs), pairs


def test_auto_pair_becomes_a_suggestion_with_explanation():
    specs = _build_specs(DS, FIELDS, VALUES)
    auto = [s for s in specs if s["type"] == "percent_of_auto"]
    assert len(auto) == 1, [s["name"] for s in specs]
    assert "найдено по данным" in auto[0]["why"]
    assert "PERCENT_OF" in auto[0]["formula"]


def test_dictionary_pair_is_not_duplicated_by_auto_rule():
    # Отправлено → доставлено уже покрыто словарём: авто-правило не должно
    # предложить то же самое второй раз.
    fields = [
        {"code": "otpr", "name": "Количество отправленных уведомлений · Факт · нарастающим итогом"},
        {"code": "dost", "name": "Количество доставленных уведомлений · Факт · нарастающим итогом"},
    ]
    values = {"otpr": VALUES["prinyato"], "dost": VALUES["vydano"]}
    specs = _build_specs(DS, fields, values)
    shares = [s for s in specs if s["type"].startswith("percent_of")]
    assert len(shares) == 1, [s["name"] for s in shares]
    assert shares[0]["type"] == "percent_of"
