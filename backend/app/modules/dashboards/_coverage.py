"""Какие графы формы показывает виджет — для подсказки «новые графы не показаны».

Виджет показывает графу тремя способами, и подсказка обязана знать все три,
иначе она «находит недостачу» там, где графа на экране есть:
  1. называет её в конфигурации — value_field, plan_field, fact_field,
     label_field, value_fields, пары полос план-факта (pairs), ряды сравнения
     источников (series);
  2. читает форму ЦЕЛИКОМ — таблица и «показатели списком» без своего списка граф;
  3. разворачивает МЕРУ — рейтинг «по мере» («Принято, ед.») берёт все графы
     с этим хвостом имени, и новая услуга попадает в него сама.
До 01.10.2026 подсказка знала только первый способ, и половины ключей в нём
(pairs, series) тоже не было: на дашборде РЦО она насчитывала 359
«непоказанных» граф, хотя таблица первичных данных показывала их все.

Способы 2 и 3 подсказка не прячет, а называет («уже видна в «…»»): таблица
показывает графу числом в одной из трёхсот колонок, а заказчик спрашивает
«добавить виджет?» — решать, хватит ли этого, человеку.

Графа принадлежит ФОРМЕ: у двух форм дашборда коды граф могут совпасть, и
графа, названная виджетом формы A, не показана тем самым для формы B (до
08.10.2026 множество названных граф было общим на все формы дашборда).
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from ._levels import WHOLE_FORM_TYPES

_KEYS = ("value_field", "plan_field", "fact_field", "label_field")


def named_fields(cfg: Optional[dict]) -> List[Tuple[str, str]]:
    """Графы, которые виджет называет в конфигурации прямо, — парами
    (форма, графа), без повторов. Ряд сравнения источников берёт графу своей
    формы; у прочих ключей форма — своя форма виджета."""
    cfg = cfg or {}
    own = cfg.get("dataset_code") or ""
    out: List[Tuple[str, str]] = []

    def add(code: str, fields: Iterable) -> None:
        for f in fields:
            if f and (code, f) not in out:
                out.append((code, f))

    add(own, (cfg.get(k) for k in _KEYS))
    add(own, cfg.get("value_fields") or [])
    for p in cfg.get("pairs") or []:
        if isinstance(p, dict):
            add(own, (p.get("plan_field"), p.get("fact_field")))
    for s in cfg.get("series") or []:
        if isinstance(s, dict):
            add(s.get("dataset_code") or own, (s.get("value_field"),))
    return out


def reads_whole_form(widget_type: Optional[str], cfg: Optional[dict]) -> bool:
    """Таблица и «показатели списком» без своего списка граф показывают все графы
    выпуска — то же условие, по которому лестница сужает их до ветки."""
    cfg = cfg or {}
    return (widget_type in WHOLE_FORM_TYPES and cfg.get("value_fields") is None
            and not cfg.get("value_field"))


def hides_zero(widget_type: Optional[str], cfg: Optional[dict]) -> bool:
    """«Показатели списком» по умолчанию прячут графы с нулём (`hide_zero`, тот
    же умолчательный True, что в расчёте виджета). Такая графа в нём НЕ видна,
    и писать «уже видна в …» про неё было бы неправдой — замер 08.10: на РЦО
    5 из 7 граф подсказки стояли в отчёте нулями."""
    return widget_type == "field_list" and bool((cfg or {}).get("hide_zero", True))


def measure_of_cfg(cfg: Optional[dict]) -> Optional[str]:
    """Мера, которую виджет разворачивает в графы, — если списка граф у него нет."""
    cfg = cfg or {}
    return cfg.get("measure") if cfg.get("measure") and not cfg.get("value_fields") else None


def dataset_codes(cfg: Optional[dict]) -> List[str]:
    """Формы, на которых стоит виджет: своя и формы рядов сравнения."""
    cfg = cfg or {}
    out: List[str] = []
    if cfg.get("dataset_code"):
        out.append(cfg["dataset_code"])
    for s in cfg.get("series") or []:
        if isinstance(s, dict) and s.get("dataset_code") and s["dataset_code"] not in out:
            out.append(s["dataset_code"])
    return out
