"""Разбор формульного DSL в AST (dict, пригодный для jsonb) + извлечение зависимостей.

Рекурсивный спуск по грамматике formula_dsl_grammar.ebnf. AST — словари вида
{"t": <тип>, ...}, чтобы напрямую класться в metric_versions.formula_ast (jsonb).

Приоритеты: expression(+,-) → term(*,/) → factor(унарный -) → power(^) → primary.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

AGG_FUNCS = {"SUM", "AVG", "COUNT", "MIN", "MAX"}
WINDOW_FUNCS = {"RUNNING_TOTAL", "PERIOD_COMPARE", "SHARE_OF_TOTAL", "PLAN_FACT_DELTA", "PLAN_FACT_PCT", "PERCENT_OF"}
DATA_REFS = {"field", "cell", "metric"}
PERIOD_UNITS = {"day", "week", "month", "quarter", "year"}
COMPARE_MODES = {"delta", "pct", "ratio"}


class FormulaError(Exception):
    """Синтаксическая или семантическая ошибка формулы."""


# --------------------------------------------------------------------------- #
# Токенизатор
# --------------------------------------------------------------------------- #
_TOKEN_RE = re.compile(r"""
    \s+
  | (?P<NUM>\d+(?:\.\d+)?)
  | (?P<STR>'(?:[^'\\]|\\.)*')
  | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<OP>[+\-*/^(),={}])
""", re.VERBOSE)


class Token:
    __slots__ = ("kind", "value", "pos")

    def __init__(self, kind: str, value: str, pos: int):
        self.kind, self.value, self.pos = kind, value, pos

    def __repr__(self) -> str:
        return f"{self.kind}({self.value!r})"


def tokenize(src: str) -> List[Token]:
    tokens: List[Token] = []
    i = 0
    while i < len(src):
        m = _TOKEN_RE.match(src, i)
        if not m or m.end() == i:
            raise FormulaError(f"Недопустимый символ в позиции {i}: {src[i]!r}")
        i = m.end()
        if m.lastgroup is None:  # пробелы
            continue
        kind = m.lastgroup
        val = m.group()
        if kind == "STR":
            val = val[1:-1].replace("\\'", "'").replace("\\\\", "\\")
        tokens.append(Token(kind, val, m.start()))
    tokens.append(Token("EOF", "", len(src)))
    return tokens


# --------------------------------------------------------------------------- #
# Парсер (рекурсивный спуск)
# --------------------------------------------------------------------------- #
class Parser:
    def __init__(self, tokens: List[Token]):
        self.toks = tokens
        self.i = 0

    def peek(self) -> Token:
        return self.toks[self.i]

    def next(self) -> Token:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect_op(self, op: str) -> None:
        t = self.peek()
        if t.kind != "OP" or t.value != op:
            raise FormulaError(f"Ожидался «{op}» в позиции {t.pos}, получено «{t.value or 'конец'}»")
        self.next()

    def is_op(self, op: str) -> bool:
        t = self.peek()
        return t.kind == "OP" and t.value == op

    # -- грамматика --
    def parse(self) -> Dict[str, Any]:
        node = self.expression()
        if self.peek().kind != "EOF":
            raise FormulaError(f"Лишние символы в позиции {self.peek().pos}: «{self.peek().value}»")
        return node

    def expression(self) -> Dict[str, Any]:
        node = self.term()
        while self.is_op("+") or self.is_op("-"):
            op = self.next().value
            node = {"t": "bin", "op": op, "l": node, "r": self.term()}
        return node

    def term(self) -> Dict[str, Any]:
        node = self.factor()
        while self.is_op("*") or self.is_op("/"):
            op = self.next().value
            node = {"t": "bin", "op": op, "l": node, "r": self.factor()}
        return node

    def factor(self) -> Dict[str, Any]:
        if self.is_op("-"):
            self.next()
            return {"t": "neg", "e": self.factor()}
        return self.power()

    def power(self) -> Dict[str, Any]:
        base = self.primary()
        if self.is_op("^"):
            self.next()
            return {"t": "pow", "base": base, "exp": self.factor()}
        return base

    def primary(self) -> Dict[str, Any]:
        t = self.peek()
        if t.kind == "NUM":
            self.next()
            return {"t": "num", "v": float(t.value)}
        if self.is_op("("):
            self.next()
            node = self.expression()
            self.expect_op(")")
            return node
        if t.kind == "IDENT":
            return self.call()
        raise FormulaError(f"Неожиданный токен «{t.value or 'конец'}» в позиции {t.pos}")

    def call(self) -> Dict[str, Any]:
        name = self.next().value
        if not self.is_op("("):
            raise FormulaError(f"Ожидались «(» после «{name}» в позиции {self.peek().pos}")
        self.expect_op("(")
        if name in AGG_FUNCS:
            node = self._agg(name)
        elif name == "field":
            node = self._field()
        elif name == "cell":
            node = self._cell()
        elif name == "metric":
            node = self._metric()
        elif name in WINDOW_FUNCS:
            node = self._window(name)
        else:
            raise FormulaError(f"Неизвестная функция «{name}»")
        self.expect_op(")")
        return node

    # -- строковый аргумент --
    def _str(self) -> str:
        t = self.peek()
        if t.kind != "STR":
            raise FormulaError(f"Ожидалась строка в кавычках в позиции {t.pos}")
        self.next()
        return t.value

    def _named_str(self, key: str) -> str:
        """Разбирает  key = 'value'  (проверяет имя ключа)."""
        t = self.next()
        if t.kind != "IDENT" or t.value != key:
            raise FormulaError(f"Ожидался параметр «{key}» в позиции {t.pos}")
        self.expect_op("=")
        return self._str()

    # -- конкретные функции --
    def _agg(self, fn: str) -> Dict[str, Any]:
        arg = self.expression()
        filt: Optional[Dict[str, str]] = None
        if self.is_op(","):
            self.next()
            filt = self._filter()
        return {"t": "agg", "fn": fn, "arg": arg, "filter": filt}

    def _filter(self) -> Dict[str, str]:
        # filter = { 'k'='v' [, 'k'='v' ...] }
        t = self.next()
        if t.kind != "IDENT" or t.value != "filter":
            raise FormulaError(f"Ожидался «filter» в позиции {t.pos}")
        self.expect_op("=")
        self.expect_op("{")
        conds: Dict[str, str] = {}
        while not self.is_op("}"):
            k = self._str()
            self.expect_op("=")
            v = self._str()
            conds[k] = v
            if self.is_op(","):
                self.next()
        self.expect_op("}")
        return conds

    def _field(self) -> Dict[str, Any]:
        dataset = self._str()
        self.expect_op(",")
        field = self._str()
        return {"t": "field", "dataset": dataset, "field": field}

    def _cell(self) -> Dict[str, Any]:
        dataset = self._str()
        self.expect_op(",")
        date = self._named_str("date")
        self.expect_op(",")
        row = self._named_str("row")
        self.expect_op(",")
        col = self._named_str("col")
        return {"t": "cell", "dataset": dataset, "date": date, "row": row, "col": col}

    def _metric(self) -> Dict[str, Any]:
        code = self._str()
        version: Any = "approved"  # по умолчанию — одобренная версия
        if self.is_op(","):
            self.next()
            t = self.next()
            if t.kind != "IDENT" or t.value != "version":
                raise FormulaError(f"Ожидался «version» в позиции {t.pos}")
            self.expect_op("=")
            v = self.next()
            if v.kind == "NUM":
                version = int(float(v.value))
            elif v.kind == "IDENT" and v.value in ("latest", "approved"):
                version = v.value
            else:
                raise FormulaError(f"Недопустимая версия метрики: «{v.value}»")
        return {"t": "metric", "code": code, "version": version}

    def _window(self, fn: str) -> Dict[str, Any]:
        if fn == "RUNNING_TOTAL":
            arg = self.expression()
            self.expect_op(",")
            grain = self._named_str("grain")
            return {"t": "running_total", "arg": arg, "grain": grain}
        if fn == "PERIOD_COMPARE":
            arg = self.expression()
            self.expect_op(",")
            unit = self._str()
            if unit not in PERIOD_UNITS:
                raise FormulaError(f"Недопустимый период «{unit}» (ожидались {sorted(PERIOD_UNITS)})")
            mode = "delta"
            if self.is_op(","):
                self.next()
                mode = self._named_str("mode")
                if mode not in COMPARE_MODES:
                    raise FormulaError(f"Недопустимый режим сравнения «{mode}»")
            return {"t": "period_compare", "arg": arg, "unit": unit, "mode": mode}
        if fn == "SHARE_OF_TOTAL":
            arg = self.expression()
            self.expect_op(",")
            over = self._named_str("over")
            return {"t": "share", "arg": arg, "over": over}
        if fn == "PERCENT_OF":
            # PERCENT_OF(база, значение) → значение/база*100 (база = 100%)
            base = self.expression()
            self.expect_op(",")
            value = self.expression()
            return {"t": "percent_of", "base": base, "value": value}
        # PLAN_FACT_DELTA / PLAN_FACT_PCT
        plan = self.expression()
        self.expect_op(",")
        fact = self.expression()
        return {"t": "plan_fact", "fn": fn, "plan": plan, "fact": fact}


def parse(expression: str) -> Dict[str, Any]:
    """Строка DSL → AST (dict)."""
    if not expression or not expression.strip():
        raise FormulaError("Пустая формула")
    return Parser(tokenize(expression)).parse()


# --------------------------------------------------------------------------- #
# Извлечение зависимостей из AST
# --------------------------------------------------------------------------- #
def extract_dependencies(ast: Dict[str, Any]) -> Dict[str, List[str]]:
    """Возвращает {'datasets': [коды датасетов], 'metrics': [коды метрик]} (без повторов)."""
    datasets: List[str] = []
    metrics: List[str] = []

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        t = node.get("t")
        if t in ("field", "cell"):
            ds = node["dataset"]
            if ds not in datasets:
                datasets.append(ds)
        elif t == "metric":
            code = node["code"]
            if code not in metrics:
                metrics.append(code)
        for key, val in node.items():
            if isinstance(val, dict):
                walk(val)
            elif isinstance(val, list):
                for it in val:
                    walk(it)

    walk(ast)
    return {"datasets": datasets, "metrics": metrics}
