"""Экспорт данных страницы в .xlsx (вынесено из _widgetdata.py)."""
from __future__ import annotations

from ._base import DashboardError
from ._rls import _can_view, visible_widget_ids
from ._widgetdata import compute_widget_data
from ._widgetsources import _page_org


async def export_page_xlsx(conn, org_id, user: dict, page_id: str) -> bytes:
    """Экспорт данных всех виджетов страницы в .xlsx (openpyxl).
    KPI/план-факт — на лист «Сводка», датасетные виджеты — по листу на виджет.
    Аннотации (text/image) пропускаются. RLS: проверяется доступ к дашборду."""
    import io
    import re

    from openpyxl import Workbook

    p = await _page_org(conn, org_id, page_id)
    if p is None:
        raise DashboardError("Страница не найдена")
    if not await _can_view(conn, org_id, user, str(p["dashboard_id"])):
        raise DashboardError("Страница не найдена")

    allowed = await visible_widget_ids(conn, org_id, user, str(p["dashboard_id"]))
    rows = await conn.fetch(
        "select id, name, widget_type from widgets where page_id=$1::uuid order by position_y, position_x", page_id)
    if allowed is not None:
        rows = [w for w in rows if str(w["id"]) in allowed]

    wb = Workbook()
    summary = wb.active
    summary.title = "Сводка"
    summary.append(["Виджет", "Тип", "Показатель", "Значение"])
    has_summary = False

    used: set = set()
    def sheet_name(base: str) -> str:
        n = re.sub(r"[\[\]:*?/\\]", " ", base or "Лист")[:28].strip() or "Лист"
        cand, i = n, 2
        while cand.lower() in used:
            cand, i = f"{n[:25]} {i}", i + 1
        used.add(cand.lower())
        return cand

    for w in rows:
        wid, t, name = str(w["id"]), w["widget_type"], w["name"]
        if t in ("text", "image"):
            continue
        try:
            data = await compute_widget_data(conn, org_id, wid, skip_acl=True)
        except DashboardError:
            continue
        if t == "kpi":
            summary.append([name, "KPI", "значение", data.get("value")]); has_summary = True
        elif t == "gauge":
            summary.append([name, "Спидометр", "значение", data.get("value")]); has_summary = True
        elif t == "plan_fact":
            summary.append([name, "План-факт", "план", data.get("plan")])
            summary.append([name, "План-факт", "факт", data.get("fact")])
            summary.append([name, "План-факт", "выполнение, %", data.get("pct")]); has_summary = True
        elif t == "table":
            ws = wb.create_sheet(sheet_name(name))
            cols = list(data.get("columns", []))
            ws.append(["Строка"] + cols)
            for r in data.get("rows", []):
                ws.append([r.get("row")] + [r.get(c) for c in cols])
        elif t in ("bar", "line", "pie"):
            ws = wb.create_sheet(sheet_name(name))
            ws.append(["Категория", "Значение"])
            for c, v in zip(data.get("categories", []), data.get("values", []), strict=False):
                ws.append([c, v])
        elif t == "dynamics":
            ws = wb.create_sheet(sheet_name(name))
            anomaly_idx = {a["index"] for a in data.get("anomalies", [])}
            ws.append(["Период", "Значение", "Аномалия"])
            for i, (pr, v) in enumerate(zip(data.get("periods", []), data.get("values", []), strict=False)):
                ws.append([pr, v, "⚠" if i in anomaly_idx else ""])
        elif t == "yoy":
            ws = wb.create_sheet(sheet_name(name))
            py, cy = data.get("previous_year"), data.get("current_year")
            ws.append(["Месяц", str(py) if py else "пред. год", str(cy)])
            for mn, pv, cv in zip(data.get("months", []), data.get("previous", []), data.get("current", []), strict=False):
                ws.append([mn, pv, cv])
        elif t in ("compare", "cross_dataset_compare"):
            ws = wb.create_sheet(sheet_name(name))
            series = data.get("series", [])
            cats = data.get("categories", [])
            ws.append(["Категория"] + [s.get("name") for s in series])
            for i, c in enumerate(cats):
                ws.append([c] + [(s.get("data") or [])[i] if i < len(s.get("data", [])) else None for s in series])
        elif t == "heatmap":
            ws = wb.create_sheet(sheet_name(name))
            cols = list(data.get("columns", []))
            rws = list(data.get("rows", []))
            grid = [[None] * len(cols) for _ in rws]
            for ci, ri, v in data.get("cells", []):
                if ri < len(rws) and ci < len(cols):
                    grid[ri][ci] = v
            ws.append(["Строка"] + cols)
            for i, rname in enumerate(rws):
                ws.append([rname] + grid[i])
        elif t == "pivot":
            ws = wb.create_sheet(sheet_name(name))
            cols = list(data.get("columns", []))
            ws.append(["Строка"] + cols + ["Итого"])
            for r in data.get("rows", []):
                ws.append([r.get("row")] + list(r.get("values", [])) + [r.get("total")])
            ws.append(["Итого"] + list(data.get("col_totals", [])) + [data.get("grand_total")])
        elif t == "waterfall":
            ws = wb.create_sheet(sheet_name(name))
            ws.append(["Категория", "Значение"])
            for c, v in zip(data.get("categories", []), data.get("values", []), strict=False):
                ws.append([c, v])
            ws.append([data.get("total_label", "Итого"), sum(v for v in data.get("values", []) if v is not None)])
        elif t == "objects_compare":
            ws = wb.create_sheet(sheet_name(name))
            ws.append(["Подразделение", "Значение"])
            for c, v in zip(data.get("categories", []), data.get("values", []), strict=False):
                ws.append([c, v])

    if not has_summary and len(wb.sheetnames) > 1:
        wb.remove(summary)  # нет KPI/план-факта, но есть датасетные листы — убираем пустую сводку

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
