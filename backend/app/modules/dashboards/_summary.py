"""Строка-резюме страницы: «как дела», а не «сколько».

Первый экран дашборда отвечает на вопрос «сколько» — числами. Руководитель
приходит с другим вопросом: «что изменилось и на что смотреть». До сих пор
ответ приходилось собирать глазами по полутора десяткам карточек.

Здесь он считается по тем же данным, что показывают виджеты: приросты берутся
из последнего и предыдущего отчёта главного набора данных страницы, план-факты
— из её виджетов. Своей арифметики нет: расходиться с карточками нечему.
"""
from __future__ import annotations

from typing import List, Optional

from ._aggregate import aggregate_series
from ._rowrls import allowed_rows_for_dataset

# Больше трёх имён в строке никто не читает — остальные считаем числом.
NAMED = 2


def _short(name: str) -> str:
    """Показатель без разреза: в резюме важен предмет, а не «нарастающим итогом»."""
    from ..metrics.data_suggestions import _clean, _split_name

    return _clean(_split_name(name)["subject"]) or name


async def page_summary(conn, org_id, page_id: str, user: dict) -> dict:
    """Что изменилось к прошлому отчёту по показателям страницы."""
    from . import service

    wl = await service.list_page_widgets(conn, org_id, page_id, user)
    hits: dict = {}
    fields: set = set()
    plan_fact: List[dict] = []
    for w in wl["widgets"]:
        cfg = w.get("config") or {}
        code = cfg.get("dataset_code")
        if not code:
            continue
        hits[code] = hits.get(code, 0) + 1
        for key in ("value_field", "fact_field"):
            if cfg.get(key):
                fields.add((code, cfg[key]))
        for f in cfg.get("value_fields") or []:
            fields.add((code, f))
        if w.get("widget_type") == "plan_fact":
            plan_fact.append(w)
    if not hits:
        return {"periods": None, "grew": 0, "fell": 0, "same": 0, "top": [], "worst": []}

    code = max(hits, key=lambda c: hits[c])
    rels = await conn.fetch(
        "select id, reporting_period_start from dataset_releases "
        "where organization_id=$1 and code=$2 and status<>'superseded' "
        "and reporting_period_start is not null "
        "order by reporting_period_start desc limit 2", org_id, code)
    if len(rels) < 2:
        # Один отчёт: сравнивать не с чем, и придумывать «динамику» нельзя.
        return {"periods": None, "grew": 0, "fell": 0, "same": 0, "top": [], "worst": [],
                "single_report": True}

    allowed = await allowed_rows_for_dataset(conn, org_id, user, code) if user is not None else None
    wanted = sorted(f for c, f in fields if c == code)
    if not wanted:
        return {"periods": None, "grew": 0, "fell": 0, "same": 0, "top": [], "worst": []}

    names = {r["code"]: r["name"] for r in await conn.fetch(
        "select code, name from canonical_fields "
        "where object_id=(select object_id from dataset_releases where id=$1) "
        "and code = any($2::text[])", rels[0]["id"], wanted)}

    async def values(rel_id) -> dict:
        params: list = [rel_id, wanted]
        acl = ""
        if allowed is not None:
            params.append(list(allowed))
            acl = " and row_label = any($3::text[])"
        rows = await conn.fetch(
            "select canonical_field_code as code, value_number as val from dataset_values "
            f"where dataset_release_id=$1 and canonical_field_code = any($2::text[]) "
            f"and value_number is not null{acl}", *params)
        buckets: dict = {}
        for r in rows:
            buckets.setdefault(r["code"], []).append(float(r["val"]))
        return {c: aggregate_series(v, names.get(c, c))[0] for c, v in buckets.items()}

    now, prev = await values(rels[0]["id"]), await values(rels[1]["id"])
    moves: List[dict] = []
    grew = fell = same = 0
    for c, v in now.items():
        p = prev.get(c)
        if p is None:
            continue
        delta = v - p
        pct = (delta / p * 100.0) if p else None
        if delta > 0:
            grew += 1
        elif delta < 0:
            fell += 1
        else:
            same += 1
        moves.append({"field": c, "name": _short(names.get(c, c)), "full_name": names.get(c, c),
                      "value": v, "delta": delta, "delta_pct": pct})

    # Один показатель — одна строка резюме: без этого «сильнее всех выросли»
    # оказывались два разреза одного и того же показателя («за неделю» и
    # «текущий месяц»), и место второго занимала копия первого.
    best: dict = {}
    for m in moves:
        if m["delta_pct"] is None:
            continue
        cur = best.get(m["name"])
        if cur is None or abs(m["delta_pct"]) > abs(cur["delta_pct"]):
            best[m["name"]] = m
    ranked = sorted(best.values(), key=lambda m: m["delta_pct"], reverse=True)
    out = {
        "period": rels[0]["reporting_period_start"].isoformat(),
        "prev_period": rels[1]["reporting_period_start"].isoformat(),
        "grew": grew, "fell": fell, "same": same,
        "top": [m for m in ranked[:NAMED] if m["delta"] > 0],
        "worst": [m for m in reversed(ranked[-NAMED:]) if m["delta"] < 0],
    }
    # План-факты страницы: их процент — отдельный ответ на «как дела».
    plans: List[dict] = []
    for w in plan_fact[:3]:
        try:
            d = await service.compute_widget_data(
                conn, org_id, str(w["id"]), None, None, None, user)
        except Exception:  # noqa: BLE001 — резюме не важнее самой страницы
            continue
        if d.get("pct") is not None:
            # Имя виджета план-факта — «Показатель: план и факт»; в строке нужен
            # сам показатель, служебный хвост только занимает место.
            plans.append({"name": _short(w["name"].split(":")[0]), "pct": d["pct"]})
    out["plans"] = plans
    return out


def _fmt_pct(v: Optional[float]) -> str:
    return "" if v is None else f"{v:+.1f}".replace(".", ",") + " %"
