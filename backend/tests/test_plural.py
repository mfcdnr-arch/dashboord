"""Склонение по числу — одна функция на весь бэкенд (08.10.2026).

Было три копии и отдельная `_plural_rows`, записанные по-разному. Страж ниже
не даёт завести четвёртую: копия расходится с оригиналом молча, а расходится
она в тексте, который читает человек («2 строк», «11 строка»).
"""
import pathlib
import re

from app.plural import plural


def test_plural_rules():
    f = lambda n: plural(n, "строка", "строки", "строк")  # noqa: E731
    assert [f(n) for n in (1, 2, 4, 5, 11, 12, 14, 21, 22, 25, 101, 111, 0)] == [
        "строка", "строки", "строки", "строк", "строк", "строк", "строк",
        "строка", "строки", "строк", "строка", "строк", "строк"]
    assert f(-1) == "строка" and f(-12) == "строк", "знак числа на склонение не влияет"


def test_no_local_copies():
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    pat = re.compile(r"^def _?plural\w*\(n: int, one", re.M)
    found = [str(p.relative_to(root)) for p in root.rglob("*.py")
             if p.name != "plural.py" and pat.search(p.read_text(encoding="utf-8"))]
    assert not found, f"своя копия склонения: {found} — берите app.plural.plural"
