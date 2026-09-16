"""Поля ввода названы, а результат действия слышен диктору (находки аудита).

Было: у полей не было имени — программа чтения с экрана говорила «поле ввода»
и всё; результат действия («сохранено», «ошибка», «пароли не совпадают»)
рисовался обычным `<div>` и объявлялся ноль раз из 285. Обе вещи чинятся
незаметно для зрячего и так же незаметно ломаются обратно, поэтому проверяются
тестом — тем же приёмом, каким `test_table_keyboard` читает исходники фронта.

Имя поля может быть дано по-разному, и все способы равноправны: `aria-label`,
`aria-labelledby`, `<label for>`, обёртка `<label>` и обёртка-компонент (в
проекте их восемь копий под именами F / L / Lbl / Field / Row — каждая
рендерит `<label>`). Placeholder считается именем, только если он называет
поле, а не показывает пример значения: «Например: SUM(…)» как имя поля
бессмысленно.
"""
import re
from pathlib import Path

_ROOTS = [Path("/frontend/src"), Path(__file__).resolve().parents[2] / "frontend" / "src"]
SRC = next((r for r in _ROOTS if r.exists()), _ROOTS[-1])

FIELD = re.compile(r"<(input|select|textarea)\b", re.I)
# компонент-обёртка: его JSX начинается с <label>, значит поле внутри названо
WRAP_DEF = re.compile(r"(?:export\s+)?(?:function|const)\s+([A-Z]\w*)\s*[=(][^\n]*\n?[^\n]*?return\s*\(?\s*<label\b", re.S)
PLACEHOLDER = re.compile(r'placeholder=(?:"([^"]*)"|\{`([^`]*)`\}|\{([^}]*)\})')
# placeholder-пример: показывает, что вписать, но полем не называется
EXAMPLE = re.compile(r"^\s*(напр\b|например|например:|https?://|…|\.\.\.)", re.I)


def _end_of_tag(src: str, i: int) -> int:
    depth = 0
    while i < len(src):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == ">" and depth == 0:
            return i
        i += 1
    return i


def _strip_comments(src: str) -> str:
    """Убрать комментарии, сохранив нумерацию строк.

    Без этого тест ловит примеры разметки в пояснениях («Дата в формате поля
    <input type="date">») и требует чинить объяснение вместо кода — ровно то
    ложное срабатывание, что уже случилось со стражем nginx.
    """
    out, i = [], 0
    while i < len(src):
        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = len(src) if j < 0 else j + 2
            out.append("\n" * src.count("\n", i, j))
            i = j
        else:
            j = src.find("\n", i)
            j = len(src) if j < 0 else j
            line = src[i:j]
            out.append("" if line.lstrip().startswith("//") else line)
            out.append("\n" if j < len(src) else "")
            i = j + 1
    return "".join(out)


def _sources() -> dict:
    return {p: _strip_comments(p.read_text(encoding="utf-8")) for p in sorted(SRC.rglob("*.tsx"))}


def _unnamed() -> list:
    texts = _sources()
    defs = {p: set(WRAP_DEF.findall(t)) for p, t in texts.items()}
    exported = {n for p, ns in defs.items() for n in ns if re.search(r"export\s+function\s+" + n + r"\b", texts[p])}
    out = []
    for p, src in texts.items():
        local = defs[p] | {n for n in exported if re.search(r"import[^\n]*\b" + n + r"\b", src)}
        labelled_ids = set(re.findall(r"htmlFor=\{([^}]*)\}", src)) | set(re.findall(r'htmlFor="([^"]*)"', src))
        for m in FIELD.finditer(src):
            tag = src[m.start():_end_of_tag(src, m.end())]
            line = src[:m.start()].count("\n") + 1
            if "aria-label" in tag:          # aria-label и aria-labelledby
                continue
            ids = set(re.findall(r"\bid=\{([^}]*)\}", tag)) | set(re.findall(r'\bid="([^"]*)"', tag))
            if ids & labelled_ids:
                continue
            ob = src.rfind("<label", 0, m.start())
            if ob >= 0 and src.find("</label>", ob) > m.start():
                continue
            if any((w_at := max(src.rfind("<" + w + " ", 0, m.start()), src.rfind("<" + w + "\n", 0, m.start()))) >= 0
                   and src.find("</" + w + ">", w_at) > m.start() for w in local):
                continue
            if re.search(r"\btitle=", tag):
                continue
            ph = PLACEHOLDER.search(tag)
            if ph:
                text = ph.group(1) or ph.group(2) or ""
                if text and not EXAMPLE.match(text):
                    continue                 # placeholder называет поле — принимаем
                if not text:
                    continue                 # placeholder из переменной — судить не можем
            out.append(f"{p.relative_to(SRC)}:{line}")
    return out


def test_every_field_is_named():
    """У каждого поля ввода есть имя: иначе диктор читает «поле ввода»."""
    bad = _unnamed()
    assert not bad, (
        "поля без имени (добавьте aria-label, свяжите label через htmlFor или "
        "оберните компонентом подписи):\n  " + "\n  ".join(bad))


def test_result_messages_go_through_notice():
    """Сообщение о результате — через Notice: роль задаётся там, в одном месте.

    Прямой `<div style={errBox}>` снова стал бы немым для диктора, а заметить
    это глазами нельзя — на экране он выглядит точно так же.
    """
    bad = []
    for p, src in _sources().items():
        if p.name == "Notice.tsx":
            continue
        for m in re.finditer(r"<div [^>]*style=\{\{?\s*\.{0,3}\s*(errBox|okBox)", src):
            bad.append(f"{p.relative_to(SRC)}:{src[:m.start()].count(chr(10)) + 1}")
    assert not bad, "сообщение выводится в обход Notice (диктор его не объявит):\n  " + "\n  ".join(bad)


def test_notice_announces_errors_and_results():
    """Ошибка прерывает чтение (alert), успех сообщается в паузе (status)."""
    src = (SRC / "components" / "Notice.tsx").read_text(encoding="utf-8")
    assert "role=" in src and "'alert'" in src and "'status'" in src, (
        "Notice должен задавать role: alert для ошибки, status для остального")
