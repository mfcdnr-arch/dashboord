"""Имена листов Excel.

31 знак — жёсткий предел формата, а имя показателя госформы («Количество
отправленных уведомлений о готовности результатов оказания услуг в МФЦ (из АИС
МФЦ в Notify) · Факт · нарастающим итогом (текущий месяц)») втрое длиннее. При
простой обрезке слева тринадцать листов «Динамики» превращались в
«Динамика  Количество поль 2 / 3 / 4»: понять, какой лист про что, нельзя.

Поэтому здесь три приёма сразу, и ни один из них не достаточен в одиночку:

1. У набора имён отсекается ОБЩЕЕ начало и общий конец по словам — тот же
   приём, что на графиках (`distinctLabels`): различие живёт в середине.
   Отсекаем, только если после этого имена не опустели и не слились.
2. Остаток ужимается по словам с обеих сторон: начало отвечает на вопрос «что
   это за виджет», хвост — «какой разрез» («за отчетную неделю»), и обрубать
   надо середину, а не конец.
3. Впереди ставится НОМЕР листа. Он и делает имена различимыми гарантированно:
   на 31 знаке добиться этого одним сокращением нельзя, а по номеру лист
   находится в листе «Содержание», где имя записано целиком.
"""
from __future__ import annotations

import re

LIMIT = 31
_FORBIDDEN = re.compile(r"[\[\]:*?/\\]")


def clean_title(name: str) -> str:
    """Убирает запрещённые в именах листов знаки и лишние пробелы."""
    s = _FORBIDDEN.sub(" ", name or "")
    s = re.sub(r"\s+", " ", s).strip(" '")
    return s or "Лист"


def _strip_common(names: list[str]) -> list[str]:
    """Отсекает общие для ВСЕХ имён начало и конец (по словам)."""
    if len(names) < 2:
        return names
    words = [n.split(" ") for n in names]
    head = 0
    while all(len(w) > head + 1 for w in words) and len({w[head] for w in words}) == 1:
        head += 1
    tail = 0
    while all(len(w) > head + tail + 1 for w in words) and len({w[-1 - tail] for w in words}) == 1:
        tail += 1
    if not head and not tail:
        return names
    cut = [" ".join(w[head: len(w) - tail]).strip() for w in words]
    # Отсечение имеет смысл, только если имена не опустели и различаются
    # не хуже прежнего: иначе лучше длинно, чем неразличимо.
    if any(not c for c in cut) or len(set(cut)) < len(set(names)):
        return names
    return cut


def _fit(text: str, limit: int) -> str:
    """Ужимает строку до `limit`, вырезая СЕРЕДИНУ по границам слов.

    Начало отвечает на вопрос «какой показатель», хвост — «какой разрез», и
    терять надо середину. Первое слово берём всегда, даже если оно длиннее
    отведённого начала: без него лист теряет предмет («Факт · за отчетную
    неделю» — это может быть что угодно).
    """
    if len(text) <= limit:
        return text
    words = [w for w in text.split(" ") if w]
    if not words:
        return text[:limit]
    hb = max(8, limit // 2)
    head = [words[0][:hb]] if len(words[0]) > hb else [words[0]]
    for w in words[1:]:
        if len(" ".join([*head, w])) > hb:
            break
        head.append(w)
    tail: list[str] = []
    for w in reversed(words[len(head):]):
        if len(" ".join(head)) + 1 + len(" ".join([w, *tail])) > limit:
            break
        tail.insert(0, w)
    # Разделитель в начале хвоста («· за отчетную неделю») смысла не несёт.
    while tail and tail[0] in ("·", "-", "—", "|"):
        tail.pop(0)
    if not tail:
        return " ".join(head)[: limit - 1] + "…"
    return " ".join(head) + "…" + " ".join(tail)


def short_cores(names: list[str], budget: int) -> list[str]:
    """Сокращённые имена БЕЗ номера — то, что реально различает листы."""
    cleaned = [clean_title(n) for n in names]
    # Общее отсекаем ВНУТРИ групп с одинаковым первым словом, а не по всему
    # набору: у «Динамика …» и «Внедрение сервиса МАХ …» общего начала нет
    # вовсе, и отсечение по всему списку не давало ничего. По группам же
    # уходит «Динамика Количество», и в имя листа помещается то, ради чего его
    # открывают: какой показатель и какой разрез.
    groups: dict[str, list[int]] = {}
    for i, c in enumerate(cleaned):
        groups.setdefault(c.split(" ")[0].lower(), []).append(i)
    cores = list(cleaned)
    for idxs in groups.values():
        if len(idxs) < 2:
            continue
        for i, core in zip(idxs, _strip_common([cleaned[i] for i in idxs]), strict=True):
            cores[i] = core
    return [_fit(c, budget) for c in cores]


def sheet_titles(names: list[str], limit: int = LIMIT) -> list[str]:
    """Имена листов для набора виджетов: номер + сокращённое имя, все разные."""
    out: list[str] = []
    used: set[str] = set()
    for i, core in enumerate(short_cores(names, limit - 3), 1):
        cand = f"{i:02d} {core}"[:limit]
        base, k = cand, 2
        while cand.lower() in used:
            cand = f"{base[: limit - 2]} {k}"
            k += 1
        used.add(cand.lower())
        out.append(cand)
    return out
