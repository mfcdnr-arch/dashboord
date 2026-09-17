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
# Компонент-подпись: функция, возвращающая <label>. Между сигнатурой и return
# могут стоять комментарии — после вырезания от них остаются ПУСТЫЕ строки, а
# прежний regex допускал не больше двух строк. Из-за этого добавленный в F
# комментарий молча вывел обёртку из списка, и 66 полей разом «потеряли»
# имя; тест при этом остался зелёным, потому что у них есть ещё и title.
# Ограничиваем длину, а не число строк, и не даём перешагнуть чужой return.
WRAP_DEF = re.compile(r"(?:export\s+)?(?:function|const)\s+([A-Z]\w*)\s*[=(](?:(?!\breturn\b)[\s\S]){0,400}?return\s*\(?\s*<label\b")
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
            # `title` именем НЕ считается: подсказка не показывается ни на
            # касании, ни при переходе клавиатурой, а часть дикторов её не
            # читает. Проверено: после починки WRAP_DEF на title не держится
            # ни одно поле — правило ужесточено без единой правки компонентов.
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


# --- заголовок страницы и текстовые альтернативы графикам (находки аудита) ---

SECTION_RE = re.compile(r"section === '(\w+)'[^<]*<([A-Z]\w*)", re.S)
IMPORT_RE = re.compile(r"import\s+(\w+)\s+from\s+'(\.[^']+)'")


def test_every_section_page_has_a_heading():
    """У каждого раздела есть заголовок первого уровня — им диктор отвечает «где я».

    Было: верхний заголовок страницы — `h2`, а `h1` не было ни на одной. По
    заголовкам листают страницу так же, как зрячий скользит взглядом, и без
    первого уровня список заголовков начинается с середины.
    """
    app = (SRC / "App.tsx").read_text(encoding="utf-8")
    imports = {name: path for name, path in IMPORT_RE.findall(app)}
    missing = []
    for section, comp in SECTION_RE.findall(app):
        rel = imports.get(comp)
        if not rel:
            continue                      # не импортированный компонент — не страница
        f = (SRC / rel.lstrip("./")).with_suffix(".tsx")
        if not f.exists():
            continue
        text = _strip_comments(f.read_text(encoding="utf-8"))
        if "<h1" in text:
            continue
        # заголовок может жить в собственной шапке раздела (открытый дашборд)
        nearby = [p for p in (SRC / "components").rglob("*.tsx")
                  if p.stem.startswith(comp.replace("Page", "")) and "<h1" in p.read_text(encoding="utf-8")]
        if not nearby:
            missing.append(f"{section} → {comp}")
    assert not missing, "разделы без заголовка первого уровня: " + ", ".join(missing)


def test_charts_have_a_text_alternative():
    """График не остаётся немым: SVG для диктора пуст, нужна подпись словами.

    Описание строится из самой опции графика в обёртке `EChart` — так его
    получает и новый тип виджета, а не только те 26, что есть сегодня.
    """
    src = _strip_comments((SRC / "components" / "EChart.tsx").read_text(encoding="utf-8"))
    assert 'role="img"' in src, "контейнер графика должен объявлять себя изображением"
    assert "aria-label" in src and "describeChart" in src, (
        "у графика должна быть текстовая альтернатива из lib/chartAlt")
