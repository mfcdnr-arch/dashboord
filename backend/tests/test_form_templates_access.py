"""Шаблоны разметки читаются и пишутся ТОЛЬКО через `ingestion/form_templates.py`.

С 09.10.2026 (миграция 061) шаблон хранится на ФОРМУ — объект + код набора, —
и у объекта их бывает несколько (книга Минэкономразвития: четыре листа). Любой
запрос вида `where object_id = $1` к таблице шаблонов после этого молча стал
неверным: `fetchrow` вернул бы произвольную форму из нескольких, а `update`
записал бы ступени одного листа во все. Таких запросов было пять в разных
модулях, и каждый следующий мог бы появиться заново, — поэтому доступ собран в
одном модуле, а этот страж не даёт завести запрос мимо него.

Смотрим строковые литералы КОДА (AST), а не текст файла: упомянуть таблицу в
пояснении можно, обратиться к ней своим SQL — нет.
"""
import ast
from pathlib import Path

APP = Path("/app/app") if Path("/app/app").exists() else Path(__file__).resolve().parents[1] / "app"
ALLOWED = {"modules/ingestion/form_templates.py"}
TABLE = "object_layout_templates"


def _literals(tree: ast.AST) -> list[tuple[int, str]]:
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
                docs.add(id(body[0].value))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def test_templates_are_accessed_only_through_form_templates():
    bad = []
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        if rel in ALLOWED:
            continue
        for line, text in _literals(ast.parse(path.read_text(encoding="utf-8"))):
            # «_history» — другая таблица; её тоже читает только модуль форм.
            if TABLE in text:
                bad.append(f"{rel}:{line}")
    assert not bad, (
        "Запрос к шаблонам разметки мимо ingestion/form_templates.py — после перехода на "
        "шаблон «объект + код набора» такой запрос берёт произвольную форму объекта: "
        + ", ".join(bad))


def test_guard_sees_sql_but_not_docstrings():
    """Страж не слеп: SQL ловится, пояснение — нет."""
    code = (
        'def f():\n'
        '    """Читает object_layout_templates — пояснение."""\n'
        '    return "select 1 from object_layout_templates where object_id = $1"\n'
    )
    found = [t for _l, t in _literals(ast.parse(code)) if TABLE in t]
    assert found == ["select 1 from object_layout_templates where object_id = $1"]
