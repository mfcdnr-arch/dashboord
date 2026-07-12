"""Смоук-тест формульного движка метрик (этап 4.1).

Запуск:  cd backend && source .venv/bin/activate && python tests/metrics_engine_smoke.py
Проверяет парсер DSL, извлечение зависимостей, детектор циклов и вычислитель
(на данных в памяти, без БД). Код возврата 1 при любом провале.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.modules.metrics import evaluator  # noqa: E402
from app.modules.metrics.cycles import CycleError, validate_and_topo_sort  # noqa: E402
from app.modules.metrics.parser import FormulaError, extract_dependencies, parse  # noqa: E402

ok = 0
fail = 0


def check(name, got, want):
    global ok, fail
    if got == want or (isinstance(want, float) and isinstance(got, float) and abs(got - want) < 1e-9):
        ok += 1
        print(f"  ✓ {name}: {got}")
    else:
        fail += 1
        print(f"  ✗ {name}: получено {got!r}, ожидалось {want!r}")


def check_raises(name, fn, substr=None):
    global ok, fail
    try:
        fn()
        fail += 1
        print(f"  ✗ {name}: ожидалась ошибка, её нет")
    except (FormulaError, CycleError) as e:
        if substr and substr not in str(e):
            fail += 1
            print(f"  ✗ {name}: ошибка есть, но без «{substr}»: {e}")
        else:
            ok += 1
            print(f"  ✓ {name}: корректно упало → {e}")


class Mem:
    """Resolver на словарях (для тестов вместо БД)."""

    def __init__(self, columns=None, cells=None, metrics=None):
        self.columns = columns or {}
        self.cells = cells or {}
        self.metrics = metrics or {}

    def column(self, dataset, field, filters):
        key = (dataset, field, tuple(sorted(filters.items()))) if filters else (dataset, field)
        return self.columns[key]

    def cell(self, dataset, date, row, col):
        return self.cells[(dataset, date, row, col)]

    def metric(self, code, version):
        return self.metrics[code]


def ev(expr, resolver=None):
    return evaluator.evaluate(parse(expr), resolver or Mem())


def main():
    print("=== 1. Арифметика и приоритеты ===")
    check("2+3*4", ev("2 + 3 * 4"), 14.0)
    check("(2+3)*4", ev("(2 + 3) * 4"), 20.0)
    check("2^3+1", ev("2 ^ 3 + 1"), 9.0)
    check("-2+5", ev("-2 + 5"), 3.0)
    check("10/4", ev("10 / 4"), 2.5)
    check("2^3^2 (право-ассоц.)", ev("2 ^ 3 ^ 2"), 512.0)

    print("=== 2. Агрегаты SUM/AVG/COUNT/MIN/MAX ===")
    r = Mem(columns={("plan", "kol"): [10.0, 20.0, 30.0]})
    check("SUM", ev("SUM(field('plan','kol'))", r), 60.0)
    check("AVG", ev("AVG(field('plan','kol'))", r), 20.0)
    check("COUNT", ev("COUNT(field('plan','kol'))", r), 3.0)
    check("MIN", ev("MIN(field('plan','kol'))", r), 10.0)
    check("MAX", ev("MAX(field('plan','kol'))", r), 30.0)

    print("=== 3. Фильтр в агрегате ===")
    rf = Mem(columns={("plan", "kol", (("usluga", "Паспорт"),)): [5.0, 7.0]})
    check("SUM+filter", ev("SUM(field('plan','kol'), filter={'usluga'='Паспорт'})", rf), 12.0)

    print("=== 4. field скаляр + ошибки ===")
    r1 = Mem(columns={("d", "x"): [42.0]})
    check("field(1 знач.)", ev("field('d','x')", r1), 42.0)
    check_raises("field(много знач.)", lambda: ev("field('plan','kol')", r), "оберните в агрегат")

    print("=== 5. cell (межпериодная ячейка) ===")
    rc = Mem(cells={
        ("nagruzka", "2026-07-10", "Паспорт РФ", "Принято"): 120.0,
        ("nagruzka", "2026-07-11", "Паспорт РФ", "Принято"): 118.0,
    })
    check("cell+cell",
          ev("cell('nagruzka', date='2026-07-10', row='Паспорт РФ', col='Принято') + "
             "cell('nagruzka', date='2026-07-11', row='Паспорт РФ', col='Принято')", rc), 238.0)

    print("=== 6. metric ref ===")
    rm = Mem(metrics={"gross": 250.0})
    check("metric()", ev("metric('gross')", rm), 250.0)
    check("metric(+10)", ev("metric('gross') + 10", rm), 260.0)
    check("metric version=latest парсится", parse("metric('gross', version=latest)")["version"], "latest")
    check("metric version=2 парсится", parse("metric('gross', version=2)")["version"], 2)

    print("=== 7. PLAN_FACT ===")
    rp = Mem(columns={("plan", "k"): [100.0], ("fakt", "k"): [90.0]})
    check("PLAN_FACT_DELTA", ev("PLAN_FACT_DELTA(SUM(field('plan','k')), SUM(field('fakt','k')))", rp), -10.0)
    check("PLAN_FACT_PCT", ev("PLAN_FACT_PCT(SUM(field('plan','k')), SUM(field('fakt','k')))", rp), 90.0)

    print("=== 8. Межфайловый расчёт ===")
    rx = Mem(columns={("a", "x"): [8.0], ("b", "y"): [2.0]})
    check("SUM(a)/SUM(b)", ev("SUM(field('a','x')) / SUM(field('b','y'))", rx), 4.0)

    print("=== 9. Извлечение зависимостей ===")
    deps = extract_dependencies(parse(
        "SUM(field('a','x')) + cell('b', date='2026-01-01', row='R', col='C') + metric('m')"))
    check("datasets", deps["datasets"], ["a", "b"])
    check("metrics", deps["metrics"], ["m"])

    print("=== 10. Циклы и топосорт ===")
    nodes = ["sales", "cogs", "margin", "margin_pct"]
    edges = [("margin", "sales"), ("margin", "cogs"), ("margin_pct", "margin")]
    order = validate_and_topo_sort(nodes, edges)
    check("margin после sales/cogs", order.index("margin") > max(order.index("sales"), order.index("cogs")), True)
    check("margin_pct последний", order.index("margin_pct") > order.index("margin"), True)
    check_raises("цикл ловится", lambda: validate_and_topo_sort(nodes, edges + [("sales", "margin_pct")]), "циклическая")

    print("=== 11. Ошибки формул ===")
    check_raises("деление на ноль", lambda: ev("1 / 0"), "ноль")
    check_raises("пустая формула", lambda: parse("   "), "Пустая")
    check_raises("мусор в конце", lambda: parse("2 + 3 )"))
    check_raises("незакрытая скобка", lambda: parse("SUM(field('a','b')"))
    check_raises("неизвестная функция", lambda: parse("FOO(1)"), "Неизвестная функция")
    check_raises("оконная → 4.2", lambda: ev("RUNNING_TOTAL(SUM(field('a','b')), grain='month')"), "4.2")

    print("=== 12. Оконные функции парсятся (AST) ===")
    check("PERIOD_COMPARE парсится", parse("PERIOD_COMPARE(metric('m'), 'month', mode='pct')")["t"], "period_compare")
    check("SHARE_OF_TOTAL парсится", parse("SHARE_OF_TOTAL(SUM(field('a','b')), over='total')")["t"], "share")

    print(f"\nИТОГ: {ok} ок, {fail} провалов")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
