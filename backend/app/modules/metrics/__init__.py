"""Модуль «Метрики» — формульный движок и показатели (KPI).

Подмодули:
- parser.py    — разбор формульного DSL в AST (jsonb) + извлечение зависимостей;
- evaluator.py — вычисление AST на реальных данных через Resolver;
- cycles.py    — детектор циклов зависимостей (DFS) + топологический порядок;
- (4.2) resolver.py/service.py/router.py — данные из dataset_values, CRUD, предпросмотр.

DSL (см. formula_dsl_grammar.ebnf, док-07):
  арифметика + - * / ^ ( );
  агрегаты SUM/AVG/COUNT/MIN/MAX(field(...)[, filter={...}]);
  ссылки field('датасет','поле'), cell('датасет', date=, row=, col=),
         metric('код'[, version=approved|latest|N]);
  окна RUNNING_TOTAL, PERIOD_COMPARE, SHARE_OF_TOTAL, PLAN_FACT_DELTA, PLAN_FACT_PCT.
"""
