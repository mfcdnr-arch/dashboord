"""Сервис дашбордов: CRUD дашбордов/страниц/виджетов + вычисление данных виджета.

Данные виджета берутся из:
- метрики (по коду, одобренная версия) — для KPI и план-факта;
- датасета (активный выпуск) — для таблицы и графиков (категория = название строки,
  значение = выбранное числовое поле).
Типы виджетов (widget_type): kpi | table | bar | line | pie | plan_fact.
"""
from __future__ import annotations

import json
from typing import List, Optional

from ... import cache
from ..audit import service as audit_svc

# Кластеры, вынесенные из этого файла (рефактор). Реэкспортируем, чтобы внешние
# вызовы `service.<name>` и `from .service import <name>` продолжали работать.
from ._alerts import (  # noqa: F401
    _ALERT_OP_TXT,
    _ALERT_STYLES,
    _alert_match,
    _alert_measure,
    _cfg,
    evaluate_alert,
)
from ._attention import page_attention  # noqa: F401
from ._base import ANNOTATION_TYPES, LAYOUT_MODES, WIDGET_TYPES, DashboardError  # noqa: F401
from ._comments import add_comment, delete_comment, list_comments  # noqa: F401
from ._describe import describe_dashboard  # noqa: F401
from ._explain import explain_widgets, widget_configs  # noqa: F401
from ._planfact import (  # noqa: F401
    PLAN_FACT_SCALE,
    build_plan_fact_dashboard,
    plan_fact_plan,
)
from ._related import widget_related  # noqa: F401
from ._report import KINDS as PROBLEM_KINDS  # noqa: F401
from ._report import report_widget_problem  # noqa: F401
from ._rls import (  # noqa: F401
    PRIVILEGED_ROLES,
    _can_view,
    _user_ctx,
    visible_dashboard_ids,
    visible_widget_ids,
)
from ._rowrank import page_row_rank  # noqa: F401
from ._rowrls import get_row_acl, set_row_acl  # noqa: F401
from ._suggest import (  # noqa: F401
    _dataset_numeric_fields,
    _existing_widget_signatures,
    _spec_signature,
    apply_default_alerts,
    auto_build,
    auto_build_plan,
    dashboard_metric_codes,
    fit_layout,
    place_metric_widget,
    suggest_widgets,
)
from ._summary import page_summary  # noqa: F401
from ._templates import (  # noqa: F401
    _remap_config,
    _template_codes,
    create_from_template,
    list_templates,
    save_as_template,
    suggest_binding,
    template_bindings,
)
from ._useraccess import set_user_dashboard_access, user_dashboard_access  # noqa: F401
from ._widgetcalc import _compute_widget  # noqa: F401
from ._widgetdata import (  # noqa: F401
    compute_page_data,
    compute_widget_data,
    list_org_alerts,
    page_report_dates,
    preview_widget,
    widget_drill,
)
from ._widgetexport import export_page_xlsx, export_widget_xlsx  # noqa: F401
from ._widgetsources import (  # noqa: F401
    _best_metric_version,
    _dataset_multi_series,
    _dataset_period_series,
    _dataset_series,
    _dataset_table,
    _formula_value,
    _metric_value,
    _page_org,
    _widget_org,
)


# --------------------------------------------------------------------------- #
# Дашборды
# --------------------------------------------------------------------------- #
async def find_dashboard_by_name(conn, org_id, name: str) -> Optional[dict]:
    """Дашборд с таким же названием уже есть? (без учёта регистра и пробелов)

    Два «Внедрения сервиса МАХ» в списке — это не мелочь оформления: человек не
    знает, какой из них открыть, а руководитель может смотреть на заброшенную
    копию и считать её актуальной. Проверку делаем ПОДСКАЗКОЙ, а не запретом:
    законный случай — копия «на 2027 год» с тем же именем в другой папке.
    """
    row = await conn.fetchrow(
        "select d.id, d.name, d.publication_status, d.created_at, d.updated_at, "
        "f.name as folder_name, o.name as object_name, u.full_name, u.login "
        "from dashboards d left join folders f on f.id=d.folder_id "
        "left join objects o on o.id=f.object_id left join users u on u.id=d.created_by "
        "where d.organization_id=$1 and lower(btrim(d.name))=lower(btrim($2)) "
        "and d.publication_status <> 'archived' order by d.created_at limit 1",
        org_id, name)
    if row is None:
        return None
    return {"dashboard_id": str(row["id"]), "name": row["name"],
            "publication_status": row["publication_status"],
            "folder_name": row["folder_name"], "object_name": row["object_name"],
            "author": row["full_name"] or row["login"],
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None}


class DuplicateDashboardName(DashboardError):
    """Дашборд с таким названием уже есть. Не запрет, а повод переспросить."""

    def __init__(self, duplicate: dict):
        self.duplicate = duplicate
        where = " / ".join(x for x in (duplicate.get("object_name"), duplicate.get("folder_name")) if x)
        super().__init__(
            f"Дашборд «{duplicate['name']}» уже есть"
            + (f" (📁 {where})" if where else "")
            + f", автор {duplicate.get('author') or '—'}. Два одинаковых названия в списке "
            "не различить — переименуйте новый или создайте копию осознанно."
        )


async def create_dashboard(conn, org_id, user_id, name: str, description: Optional[str],
                           folder_id: Optional[str], force: bool = False) -> dict:
    """Создать дашборд. При совпадении названия — отказ с переспросом.

    Проверка стоит ЗДЕСЬ, а не в обработчике запроса, потому что дашборд
    создают пять разных путей: вручную, мастером авто-сборки, сводным
    «План/факт», из шаблона и переносом на другой объект. Раньше проверял
    только ручной, и мастер молча завёл заказчику три «Дашборд «ИТ»» —
    в списке и в отчёте о популярности они неразличимы.

    Именно переспрос, а не запрет: копия «на следующий год» с тем же именем
    в другой папке законна, и решать это человеку.
    """
    if not force:
        dup = await find_dashboard_by_name(conn, org_id, name)
        if dup is not None:
            raise DuplicateDashboardName(dup)
    row = await conn.fetchrow(
        "insert into dashboards(organization_id, name, description, folder_id, created_by) "
        "values($1,$2,$3,$4::uuid,$5) returning id, name, description, publication_status, created_at",
        org_id, name, description, folder_id, user_id,
    )
    return dict(row)


async def list_dashboards(conn, org_id, user: dict, q: Optional[str] = None,
                          fav_only: bool = False, limit: int = 50, offset: int = 0,
                          from_date: Optional[str] = None, to_date: Optional[str] = None,
                          folder_id: Optional[str] = None,
                          document_id: Optional[str] = None) -> dict:
    """Постранично: {total, limit, offset, items}. Видимость через RLS
    (visible_dashboard_ids). q — поиск по названию дашборда ИЛИ названию его
    страницы (ilike); from_date/to_date — по дате последнего изменения
    (updated_at); fav_only — только избранные; folder_id — фильтр «банк
    отделов» (волна D): пусто=все, 'none'=без папки, иначе конкретная папка.
    Избранные всегда сверху; поиск/фильтр применяются на сервере."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    visible = await visible_dashboard_ids(conn, org_id, user)
    if not visible:
        return {"total": 0, "limit": limit, "offset": offset, "items": []}
    # $1=org, $2=visible ids, $3=user (для favorites). Далее — динамические фильтры.
    # Архивные дашборды в основном списке не показываем — для них раздел «Архив»
    # (вернуть в работу можно оттуда: «↩ Вернуть из архива»).
    where = "d.organization_id=$1 and d.id = any($2::uuid[]) and d.publication_status <> 'archived'"
    params: list = [org_id, list(visible), user["id"]]
    if q and q.strip():
        params.append(f"%{q.strip()}%")
        where += (f" and (d.name ilike ${len(params)} or exists ("
                  f"select 1 from dashboard_pages p2 where p2.dashboard_id=d.id and p2.name ilike ${len(params)}))")
    if from_date:
        params.append(from_date); where += f" and d.updated_at::date >= ${len(params)}::text::date"
    if to_date:
        params.append(to_date); where += f" and d.updated_at::date <= ${len(params)}::text::date"
    if folder_id == "none":
        where += " and d.folder_id is null"
    elif folder_id:
        params.append(folder_id); where += f" and d.folder_id=${len(params)}::uuid"
    if document_id:
        # «Какие дашборды построены на данных этого отчёта». Под одним кодом
        # лежит ВЕСЬ ряд недельных файлов, поэтому совпадений два вида, и
        # оба настоящие: виджет закреплён именно за этой отчётной датой
        # (дашборд-срез) либо просто читает эту форму. Отбираем оба, а какой
        # именно — говорит признак `pinned_to_document` ниже: иначе список
        # выглядел бы одинаково для любого файла папки и вводил бы в
        # заблуждение.
        params.append(document_id)
        where += (f" and exists (select 1 from widgets w "
                  f" join dataset_releases r on r.code = w.config->>'dataset_code' "
                  f" join document_versions dv on dv.id = r.source_document_version_id "
                  f" where w.dashboard_id=d.id and r.organization_id=d.organization_id "
                  f"   and dv.document_id=${len(params)}::uuid)")
    fav_join = "join" if fav_only else "left join"
    total = await conn.fetchval(
        f"select count(*) from dashboards d "
        f"{fav_join} dashboard_favorites f on f.dashboard_id=d.id and f.user_id=$3 "
        f"where {where}", *params)
    rows = await conn.fetch(
        "select d.id, d.name, d.description, d.publication_status, d.created_at, d.updated_at, "
        "d.folder_id, fo.name as folder_name, ob.name as object_name, "
        "(select count(*) from dashboard_pages p where p.dashboard_id=d.id) as pages, "
        "(select count(*) from dashboard_comments c where c.dashboard_id=d.id) as comments_count, "
        "d.featured, "
        "(f.dashboard_id is not null) as is_favorite"
        + (
            # Закреплён ли дашборд за отчётной датой ЭТОГО файла: так
            # различаются «собран по этому отчёту» и «читает эту форму».
            ", exists(select 1 from widgets w2 join documents doc2 on doc2.id=$%d::uuid "
            " where w2.dashboard_id=d.id "
            "   and w2.config->>'period' = doc2.reporting_period_start::text) as pinned_to_document "
            % len(params) if document_id else " "
        ) + 
        f"from dashboards d {fav_join} dashboard_favorites f on f.dashboard_id=d.id and f.user_id=$3 "
        "left join folders fo on fo.id=d.folder_id left join objects ob on ob.id=fo.object_id "
        f"where {where} order by is_favorite desc, d.name "
        f"limit ${len(params) + 1} offset ${len(params) + 2}",
        *params, limit, offset,
    )
    return {"total": total, "limit": limit, "offset": offset, "items": [dict(r) for r in rows]}


# Сколько отчётов помним в «Недавно смотрели» и как далеко назад смотрим.
# Полоса над списком — способ вернуться туда, где человек был вчера, а не
# второй список отчётов: пять-шесть плиток читаются с одного взгляда, два
# десятка снова требуют искать глазами. Окно в 30 дней: «недавно» дальше
# этого срока уже не «недавно», а история — она живёт в разделе «Отчёты».
RECENT_LIMIT = 6
RECENT_DAYS = 30


async def list_recent(conn, org_id, user: dict, limit: int = RECENT_LIMIT) -> dict:
    """«Недавно смотрел» — последние открытые ЭТИМ человеком отчёты.

    Своей таблицы для этого не заводим: просмотры уже пишутся в журнал
    (`audit_log`, action=view) — тот же источник, по которому считается отчёт
    популярности. Второй счётчик рядом с ним однажды разошёлся бы с первым,
    и на вопрос «сколько раз открывали» появилось бы два разных ответа.

    Видимость — та же `visible_dashboard_ids`, что и в общем списке: отчёт, к
    которому доступ отозвали, из «недавних» пропадает. Удалённые отчёты
    отсеиваются самим join'ом: в журнале их просмотры остаются (он отвечает
    на вопрос «что было»), но открывать уже нечего. Архивные тоже не
    показываем — для них отдельный раздел.

    Отметка времени берётся из журнала, а он пишется с окном в
    `VIEW_THROTTLE_MINUTES`: повторное открытие того же отчёта в пределах
    этого окна отдельной записи не создаёт, поэтому «смотрели» может отставать
    на эти минуты. Для полосы «куда вернуться» это несущественно, а вот
    второй, точный журнал ради неё заводить незачем.
    """
    limit = max(1, min(limit, 20))
    visible = await visible_dashboard_ids(conn, org_id, user)
    if not visible:
        return {"items": []}
    rows = await conn.fetch(
        "select d.id, d.name, d.description, d.publication_status, "
        "  fo.name as folder_name, ob.name as object_name, "
        "  (f.dashboard_id is not null) as is_favorite, "
        "  max(a.created_at) as viewed_at "
        "from audit_log a "
        "join dashboards d on d.id=a.entity_id and d.organization_id=$1 "
        "  and d.publication_status <> 'archived' "
        "left join folders fo on fo.id=d.folder_id "
        "left join objects ob on ob.id=fo.object_id "
        "left join dashboard_favorites f on f.dashboard_id=d.id and f.user_id=$3 "
        "where a.organization_id=$1 and a.action='view' and a.entity_type='dashboard' "
        "  and a.actor_user_id=$3 and a.entity_id = any($2::uuid[]) "
        "  and a.created_at > now() - ($4 || ' days')::interval "
        "group by d.id, d.name, d.description, d.publication_status, "
        "  fo.name, ob.name, f.dashboard_id "
        "order by viewed_at desc limit $5",
        org_id, list(visible), user["id"], str(RECENT_DAYS), limit)
    return {"items": [dict(r) for r in rows]}


async def list_featured(conn, org_id, user: dict) -> dict:
    """Подборка «Руководителю»: отмеченные дашборды, которые видит этот человек.

    Отдельной системы прав здесь НЕТ и не будет: кто что видит, решают те же
    гранты, что и в общем списке (`visible_dashboard_ids`). Флаг `featured`
    отвечает только на вопрос «показывать ли дашборд в подборке» — иначе рядом
    с грантами появился бы второй источник правды о доступе.

    Опубликованные первыми: руководителю нельзя подсунуть черновик, который
    ещё правят, — но и прятать его от автора незачем, поэтому черновик виден
    тому, кто и так имеет к нему доступ, с явной пометкой статуса.
    """
    visible = await visible_dashboard_ids(conn, org_id, user)
    if not visible:
        return {"items": []}
    rows = await conn.fetch(
        "select d.id, d.name, d.description, d.publication_status, d.updated_at, "
        "  fo.name as folder_name, ob.name as object_name, d.featured_order, "
        "  (select count(*) from dashboard_pages p where p.dashboard_id=d.id) as pages "
        "from dashboards d "
        "left join folders fo on fo.id=d.folder_id left join objects ob on ob.id=fo.object_id "
        "where d.organization_id=$1 and d.id = any($2::uuid[]) and d.featured "
        "  and d.publication_status <> 'archived' "
        "order by d.featured_order, d.name", org_id, list(visible))
    items = [dict(r) for r in rows]
    for it in items:
        it["highlights"] = await _featured_highlights(conn, org_id, user, str(it["id"]))
    return {"items": items}


# Сколько цифр показываем на плитке подборки. Руководителю нужен ответ «как
# дела», а не весь дашборд: три числа читаются с одного взгляда, десять
# превращают подборку во второй дашборд, ради которого её и не делали.
MAX_HIGHLIGHTS = 3


async def _featured_highlights(conn, org_id, user: dict, dashboard_id: str) -> list:
    """Главные цифры дашборда — прямо на плитке подборки.

    Без них руководителю приходится открывать каждый отчёт, чтобы понять, куда
    смотреть. Берём одиночные показатели (карточка, спидометр, план-факт) с
    ПЕРВОЙ страницы — она и задумана как «Обзор», — и считаем их тем же кодом,
    что рисует сами виджеты: разойтись с дашбордом плитка не может.

    Сбой расчёта одного показателя не должен ронять всю подборку: на плитке
    просто станет меньше цифр, а сам отчёт по-прежнему открывается.
    """
    rows = await conn.fetch(
        "select w.id, w.name, w.widget_type, w.config from widgets w "
        "join dashboard_pages p on p.id=w.page_id "
        "where w.dashboard_id=$1::uuid and w.widget_type = any($2::text[]) "
        "order by p.position, w.position_y, w.position_x limit $3",
        dashboard_id, ["kpi", "gauge", "plan_fact"], MAX_HIGHLIGHTS)
    out = []
    for w in rows:
        try:
            # user — ИМЕНОВАННЫМ: позиционно он попадал в from_date, и расчёт
            # молча падал на проверке доступа (плитка выходила без цифр).
            data = await compute_widget_data(conn, org_id, str(w["id"]), user=user)
        except Exception:  # noqa: BLE001 — плитка важнее одной цифры на ней
            continue
        value = data.get("value")
        if value is None and data.get("fact") is not None:
            value = data.get("fact")
        if value is None:
            continue
        out.append({
            "name": w["name"], "value": value, "unit": data.get("unit"),
            # Прирост к прошлому отчёту и сработавший порог — это и есть ответ
            # «хорошо или плохо», ради которого руководитель сюда пришёл.
            # У полосы «план и факт» роль такого ответа играет процент
            # выполнения: само по себе «7 078» не говорит, много это или мало.
            "delta_pct": data.get("delta_pct") if data.get("delta_pct") is not None
                         else await _highlight_delta(conn, org_id, w["config"], value),
            "plan_pct": data.get("pct") if data.get("type") == "plan_fact" else None,
            "alert": (data.get("alert") or {}).get("level"),
        })
    return out


async def _highlight_delta(conn, org_id, cfg, value) -> Optional[float]:
    """Прирост к прошлому отчёту, даже если у виджета он не включён.

    Показ прироста — настройка КАРТОЧКИ, и у дашбордов, собранных до её
    появления, он выключен. Но на плитке руководителя голое число не отвечает
    на его единственный вопрос — «хорошо или плохо», — поэтому здесь прирост
    считаем сами по тому же ряду периодов, что рисует «Динамика».
    """
    if isinstance(cfg, str):
        cfg = json.loads(cfg)
    code, field = (cfg or {}).get("dataset_code"), (cfg or {}).get("value_field")
    if not code or not field or value is None:
        return None
    try:
        series = await _dataset_period_series(conn, org_id, code, field)
    except Exception:  # noqa: BLE001 — прирост необязателен, число уже есть
        return None
    values = [v for _p, v in (series or []) if v is not None]
    if len(values) < 2 or not values[-2]:
        return None
    return round((values[-1] - values[-2]) / values[-2] * 100, 2)


async def featured_candidates(conn, org_id, user: dict) -> dict:
    """Что можно вынести в подборку «Руководителю» — и что система советует.

    Состав подборки набирался галочкой в общем списке дашбордов, то есть
    администратор должен был сам помнить, какие отчёты вообще есть и какие из
    них годятся руководителю. Здесь тот же выбор сделан списком с подсказкой.

    **Совет — это не решение.** Система смотрит только на проверяемые признаки:
    опубликован ли отчёт, есть ли в нём числовые показатели (иначе плитка
    подборки будет пустой), задано ли описание и смотрят ли его вообще.
    Отмечает галочки человек: «полезно руководителю» — суждение, а не факт.

    **Доступ отметкой НЕ выдаётся** (это правило подборки с самого начала),
    поэтому рядом показано, скольким людям отчёт реально виден: иначе можно
    вынести в подборку дашборд, которого руководитель всё равно не увидит.
    """
    visible = await visible_dashboard_ids(conn, org_id, user)
    if not visible:
        return {"items": []}
    rows = await conn.fetch(
        "select d.id, d.name, d.description, d.publication_status, d.featured, d.featured_order, "
        "  fo.name as folder_name, ob.name as object_name, "
        "  (select count(*) from widgets w where w.dashboard_id=d.id) as widgets, "
        "  (select count(*) from widgets w where w.dashboard_id=d.id "
        "     and w.widget_type = any($3::text[])) as number_widgets, "
        "  (select count(*) from audit_log a where a.entity_id=d.id and a.action='view' "
        "     and a.created_at >= now() - interval '30 days') as views_30d, "
        # Кому отчёт реально виден: привилегированные роли видят всё, автор —
        # своё, остальные — по гранту и только опубликованное (те же правила,
        # что и в visible_dashboard_ids).
        "  (select count(distinct u.id) from users u where u.organization_id=$1 and u.is_active and ("
        "     exists(select 1 from user_roles ur join roles r on r.id=ur.role_id "
        "            where ur.user_id=u.id and r.code = any($4::text[])) "
        "     or u.id = d.created_by "
        "     or (d.publication_status='published' and exists("
        "         select 1 from access_grants g where g.dashboard_id=d.id and g.scope='dashboard' and ("
        "            (g.grantee_type='user' and g.user_id=u.id) "
        "            or (g.grantee_type='role' and exists(select 1 from user_roles ur2 "
        "                where ur2.user_id=u.id and ur2.role_id=g.role_id)))))"
        "  )) as visible_to "
        "from dashboards d "
        "left join folders fo on fo.id=d.folder_id left join objects ob on ob.id=fo.object_id "
        "where d.organization_id=$1 and d.id = any($2::uuid[]) and d.publication_status <> 'archived' "
        "order by d.featured desc, d.featured_order, d.name",
        org_id, list(visible), ["kpi", "gauge", "plan_fact"], sorted(PRIVILEGED_ROLES))
    items = []
    for r in rows:
        why, blockers = [], []
        published = r["publication_status"] == "published"
        if published:
            why.append("опубликован")
        else:
            blockers.append("не опубликован — руководителю попадёт неутверждённое")
        if r["number_widgets"]:
            why.append(f"показателей с цифрами: {r['number_widgets']}")
        else:
            blockers.append("нет числовых показателей — плитка будет без цифр")
        if r["description"]:
            why.append("есть описание")
        else:
            blockers.append("нет описания — по названию не понять, что внутри")
        if r["views_30d"]:
            why.append(f"смотрели {r['views_30d']} раз за месяц")
        if not r["visible_to"]:
            blockers.append("никому не выдан доступ — в подборке его никто не увидит")
        items.append({
            "id": str(r["id"]), "name": r["name"], "description": r["description"],
            "publication_status": r["publication_status"], "featured": r["featured"],
            "folder_name": r["folder_name"], "object_name": r["object_name"],
            "widgets": r["widgets"], "number_widgets": r["number_widgets"],
            "views_30d": r["views_30d"], "visible_to": r["visible_to"],
            # Советуем только то, что заведомо не подведёт: опубликовано, есть
            # что показать и есть кому смотреть.
            "recommended": bool(published and r["number_widgets"] and r["visible_to"]
                                and not r["featured"]),
            "why": why, "blockers": blockers,
        })
    return {"items": items}


async def set_featured_bulk(conn, org_id, user: dict, featured: list, unfeatured: list) -> dict:
    """Пакетное изменение состава подборки: применяем разницу, а не весь список.

    Идемпотентно — повторная отметка уже отмеченного не ошибка: панель шлёт
    разницу целиком, и падать на одной строке из десяти значило бы оставить
    подборку наполовину настроенной.
    """
    visible = await visible_dashboard_ids(conn, org_id, user)
    changed = {"featured": 0, "unfeatured": 0}
    for did in (featured or []):
        if str(did) not in visible:
            raise DashboardError("Дашборд не найден")
        res = await conn.execute(
            "update dashboards set featured=true where id=$1::uuid and organization_id=$2 and not featured",
            did, org_id)
        changed["featured"] += 1 if str(res).endswith("1") else 0
    for did in (unfeatured or []):
        if str(did) not in visible:
            raise DashboardError("Дашборд не найден")
        res = await conn.execute(
            "update dashboards set featured=false where id=$1::uuid and organization_id=$2 and featured",
            did, org_id)
        changed["unfeatured"] += 1 if str(res).endswith("1") else 0
    return changed


async def featured_access(conn, org_id, user: dict) -> dict:
    """Кому открыта подборка «Руководителю» целиком, а кому — частично.

    Состав подборки и доступ к отчётам — РАЗНЫЕ вещи, и такими остаются: иначе
    достаточно было бы отметить отчёт, чтобы его увидели все, а решение «кому
    показывать» перестало бы быть решением. Но выдавать доступ по одному
    дашборду, когда подборка собрана целиком, — работа впустую, поэтому здесь
    видно, у кого сколько из подборки открыто, и доступ выдаётся пакетом.
    """
    visible = await visible_dashboard_ids(conn, org_id, user)
    dashboards = await conn.fetch(
        "select d.id, d.name, d.publication_status from dashboards d "
        "where d.organization_id=$1 and d.featured and d.publication_status <> 'archived' "
        + ("and d.id = any($2::uuid[]) " if visible else "and false ")
        + "order by d.featured_order, d.name",
        *( [org_id, list(visible)] if visible else [org_id] ))
    ids = [str(d["id"]) for d in dashboards]
    users = await conn.fetch(
        "select u.id, u.login, u.full_name, "
        # Сколько дашбордов подборки человеку уже доступно — по личным грантам
        # и по грантам на его роли: иначе администратор выдавал бы то, что уже
        # выдано, и не понимал бы, почему ничего не изменилось.
        "  (select count(distinct g.dashboard_id) from access_grants g "
        "   where g.scope='dashboard' and g.dashboard_id = any($2::uuid[]) and ("
        "     (g.grantee_type='user' and g.user_id=u.id) "
        "     or (g.grantee_type='role' and exists(select 1 from user_roles ur "
        "         where ur.user_id=u.id and ur.role_id=g.role_id)))) as has, "
        "  exists(select 1 from user_roles ur join roles r on r.id=ur.role_id "
        "         where ur.user_id=u.id and r.code = any($3::text[])) as privileged "
        "from users u where u.organization_id=$1 and u.is_active order by u.login",
        org_id, ids, sorted(PRIVILEGED_ROLES))
    roles = await conn.fetch(
        "select r.id, r.code, r.name, "
        "  (select count(*) from user_roles ur where ur.role_id=r.id) as members, "
        "  (select count(distinct g.dashboard_id) from access_grants g "
        "   where g.scope='dashboard' and g.dashboard_id = any($2::uuid[]) "
        "     and g.grantee_type='role' and g.role_id=r.id) as has "
        "from roles r where r.organization_id=$1 order by r.name", org_id, ids)
    return {
        "dashboards": [{"id": str(d["id"]), "name": d["name"],
                        "publication_status": d["publication_status"]} for d in dashboards],
        "users": [{"id": str(u["id"]), "login": u["login"], "full_name": u["full_name"],
                   "has": u["has"], "privileged": u["privileged"]} for u in users],
        "roles": [{"id": str(r["id"]), "code": r["code"], "name": r["name"],
                   "members": r["members"], "has": r["has"]} for r in roles],
    }


async def grant_featured_access(conn, org_id, actor_id, user: dict,
                                user_ids: list, role_ids: list,
                                dashboard_ids: Optional[list] = None) -> dict:
    """Выдать доступ к отчётам подборки выбранным сотрудникам и ролям.

    Пишем теми же `add_grant`, что и окно «🔒 Доступ» на дашборде: журнал
    аудита не должен зависеть от того, каким экраном воспользовались. Уже
    выданное пропускаем молча — операция пакетная, и падать на одной паре из
    двадцати значило бы выдать доступ наполовину.
    """
    visible = await visible_dashboard_ids(conn, org_id, user)
    rows = await conn.fetch(
        "select id from dashboards where organization_id=$1 and featured "
        "and publication_status <> 'archived'", org_id)
    targets = [str(r["id"]) for r in rows if str(r["id"]) in visible]
    if dashboard_ids:
        chosen = {str(x) for x in dashboard_ids}
        unknown = chosen - set(targets)
        if unknown:
            raise DashboardError("Дашборд не найден")
        targets = [d for d in targets if d in chosen]
    if not targets:
        raise DashboardError("В подборке нет отчётов, к которым можно выдать доступ")

    granted = 0
    for did in targets:
        for uid in (user_ids or []):
            if await conn.fetchval(
                    "select 1 from access_grants where dashboard_id=$1::uuid and scope='dashboard' "
                    "and grantee_type='user' and user_id=$2::uuid", did, uid):
                continue
            await add_grant(conn, org_id, actor_id, did, "user", None, uid)
            granted += 1
        for rid in (role_ids or []):
            if await conn.fetchval(
                    "select 1 from access_grants where dashboard_id=$1::uuid and scope='dashboard' "
                    "and grantee_type='role' and role_id=$2::uuid", did, rid):
                continue
            await add_grant(conn, org_id, actor_id, did, "role", rid, None)
            granted += 1
    return {"granted": granted, "dashboards": len(targets)}


async def set_featured(conn, org_id, dashboard_id: str, featured: bool,
                       order: Optional[int] = None) -> dict:
    """Включить/выключить дашборд в подборке «Руководителю»."""
    exists = await conn.fetchval(
        "select 1 from dashboards where id=$1::uuid and organization_id=$2", dashboard_id, org_id)
    if not exists:
        raise DashboardError("Дашборд не найден")
    await conn.execute(
        "update dashboards set featured=$2, featured_order=coalesce($3, featured_order), "
        "updated_at=now() where id=$1::uuid", dashboard_id, featured, order)
    return {"featured": featured}


async def set_folder(conn, org_id, dashboard_id: str, folder_id: Optional[str]) -> dict:
    """Переместить дашборд в папку («банк отделов», волна D) или убрать из
    папки (folder_id=None). Папка должна принадлежать той же организации."""
    exists = await conn.fetchval(
        "select 1 from dashboards where id=$1::uuid and organization_id=$2", dashboard_id, org_id)
    if not exists:
        raise DashboardError("Дашборд не найден")
    if folder_id:
        ok = await conn.fetchval(
            "select 1 from folders where id=$1::uuid and organization_id=$2", folder_id, org_id)
        if not ok:
            raise DashboardError("Папка не найдена")
    await conn.execute(
        "update dashboards set folder_id=$2::uuid, updated_at=now() where id=$1::uuid", dashboard_id, folder_id)
    return {"folder_id": folder_id}


async def set_favorite(conn, org_id, user: dict, dashboard_id: str, on: bool) -> dict:
    """Добавить/убрать дашборд из избранного (только видимый пользователю)."""
    if not await _can_view(conn, org_id, user, dashboard_id):
        raise DashboardError("Дашборд не найден")
    if on:
        await conn.execute(
            "insert into dashboard_favorites(user_id, dashboard_id) values($1,$2::uuid) "
            "on conflict do nothing", user["id"], dashboard_id)
    else:
        await conn.execute(
            "delete from dashboard_favorites where user_id=$1 and dashboard_id=$2::uuid",
            user["id"], dashboard_id)
    return {"dashboard_id": dashboard_id, "is_favorite": on}


async def get_dashboard(conn, org_id, user: dict, dashboard_id: str) -> dict:
    if not await _can_view(conn, org_id, user, dashboard_id):
        raise DashboardError("Дашборд не найден")
    d = await conn.fetchrow(
        "select d.id, d.name, d.description, d.publication_status, d.auto_archive, d.suggest_new_fields, "
        "d.created_at, d.updated_at, "
        "d.folder_id, fo.name as folder_name, ob.name as object_name, "
        "(select count(*) from dashboard_comments c where c.dashboard_id=d.id) as comments_count "
        "from dashboards d left join folders fo on fo.id=d.folder_id left join objects ob on ob.id=fo.object_id "
        "where d.id=$1::uuid and d.organization_id=$2", dashboard_id, org_id,
    )
    if d is None:
        raise DashboardError("Дашборд не найден")
    pages = await conn.fetch(
        "select id, name, description, position, layout_mode, period from dashboard_pages "
        "where dashboard_id=$1::uuid order by position, created_at", dashboard_id,
    )
    return {"dashboard": dict(d), "pages": [dict(p) for p in pages]}


def _widget_dataset_codes(configs) -> set:
    """Коды датасетов, на которых стоит дашборд (из конфигураций виджетов)."""
    codes: set = set()
    for cfg in configs:
        c = json.loads(cfg) if isinstance(cfg, str) else (cfg or {})
        if c.get("dataset_code"):
            codes.add(c["dataset_code"])
        for s in c.get("series") or []:
            if isinstance(s, dict) and s.get("dataset_code"):
                codes.add(s["dataset_code"])
    return codes


async def dashboard_freshness(conn, org_id, dashboard_id: str) -> dict:
    """Дата самых свежих данных под дашбордом.

    Виджеты читают последний неотменённый выпуск, то есть цифры обновляются
    сами. Но открытый на экране дашборд об этом не знает: руководитель, не
    закрывший вкладку, смотрит на вчерашние числа и уверен, что они сегодняшние.
    Лёгкий запрос (одна строка) позволяет странице раз в минуту спросить «не
    появилось ли свежее» и предложить обновиться — без перезагрузки данных.
    """
    configs = await conn.fetch(
        "select config from widgets where dashboard_id=$1::uuid", dashboard_id)
    codes = _widget_dataset_codes([c["config"] for c in configs])
    if not codes:
        return {"as_of": None, "datasets": 0}
    row = await conn.fetchrow(
        "select max(reporting_period_start) as as_of, count(*) as releases "
        "from dataset_releases where organization_id=$1 and code = any($2::text[]) "
        "and status <> 'superseded'", org_id, list(codes))
    return {
        "as_of": row["as_of"].isoformat() if row and row["as_of"] else None,
        "datasets": len(codes),
        "releases": int(row["releases"]) if row else 0,
    }


async def missing_dashboard_fields(conn, org_id, dashboard_id: str) -> dict:
    """Показатели, которые есть в данных, но не показаны на дашборде.

    Форма со временем прирастает графами, а дашборд остаётся прежним — и никто
    об этом не узнаёт, пока кто-нибудь не сверит их вручную. Система подсказывает,
    но НЕ добавляет виджеты сама: дашборд, который сам себе дорисовывает
    карточки, однажды поедет вёрсткой прямо на совещании.
    """
    configs = await conn.fetch("select config from widgets where dashboard_id=$1::uuid", dashboard_id)
    codes = _widget_dataset_codes([c["config"] for c in configs])
    if not codes:
        return {"fields": [], "count": 0}

    used: set = set()
    for c in configs:
        cfg = json.loads(c["config"]) if isinstance(c["config"], str) else (c["config"] or {})
        for key in ("value_field", "plan_field", "fact_field", "label_field"):
            if cfg.get(key):
                used.add(cfg[key])
        for f in cfg.get("value_fields") or []:
            used.add(f)
        for s in cfg.get("series") or []:
            if isinstance(s, dict) and s.get("value_field"):
                used.add(s["value_field"])

    rows = await conn.fetch(
        "select distinct v.canonical_field_code as code, cf.name, r.code as dataset_code "
        "from dataset_releases r "
        "join dataset_values v on v.dataset_release_id = r.id and v.value_number is not null "
        "left join canonical_fields cf on cf.object_id = r.object_id and cf.code = v.canonical_field_code "
        "where r.organization_id=$1 and r.code = any($2::text[]) and r.status <> 'superseded'",
        org_id, list(codes))
    missing = [
        {"code": r["code"], "name": r["name"] or r["code"], "dataset_code": r["dataset_code"]}
        for r in rows if r["code"] not in used
    ]
    missing.sort(key=lambda f: f["name"])
    return {"fields": missing, "count": len(missing)}


async def _owns_dashboard(conn, org_id, dashboard_id: str) -> bool:
    return bool(await conn.fetchval(
        "select 1 from dashboards where id=$1::uuid and organization_id=$2", dashboard_id, org_id))


async def _assert_editable(conn, dashboard_id) -> None:
    """Правки контента запрещены, пока дашборд на проверке (review) — иначе
    опубликуется не то, что проверил модератор. Отзовите заявку для изменений."""
    st = await conn.fetchval("select publication_status from dashboards where id=$1::uuid", dashboard_id)
    if st == "review":
        raise DashboardError("Дашборд на проверке — правки заблокированы; отзовите заявку, чтобы изменить")


async def update_dashboard(conn, org_id, user: dict, dashboard_id: str, patch: dict) -> dict:
    """Правка названия и описания дашборда.

    До этого имя задавалось при создании и оставалось навсегда — опечатку в
    названии исправить было нечем. Права те же, что у удаления: чужой дашборд
    правит только администратор, свой — и модератор. Аудит писать вручную не
    надо: на таблице висит триггер `trg_audit_dashboards`.

    Частичность через `exclude_unset` на роутере: описание можно стереть
    (передать null), не трогая имя.
    """
    d = await conn.fetchrow(
        "select name, created_by from dashboards where id=$1::uuid and organization_id=$2",
        dashboard_id, org_id)
    if d is None:
        raise DashboardError("Дашборд не найден")

    roles = set(user.get("roles") or ())
    if not roles & {"admin", "superadmin"} and str(d["created_by"]) != str(user["id"]):
        raise DashboardError("Недостаточно прав: чужой дашборд может изменить только администратор")

    sets, params = [], []
    if "name" in patch:
        name = (patch["name"] or "").strip()
        if not name:
            raise DashboardError("Название не может быть пустым")
        params.append(name)
        sets.append(f"name=${len(params)}")
    if "description" in patch:
        desc = patch["description"]
        params.append(desc.strip() if isinstance(desc, str) and desc.strip() else None)
        sets.append(f"description=${len(params)}")
    if "suggest_new_fields" in patch:
        params.append(bool(patch["suggest_new_fields"]))
        sets.append(f"suggest_new_fields=${len(params)}")
    if not sets:
        raise DashboardError("Нечего изменять")

    params.extend([dashboard_id, org_id])
    row = await conn.fetchrow(
        f"update dashboards set {', '.join(sets)}, updated_at=now() "
        f"where id=${len(params) - 1}::uuid and organization_id=${len(params)} "
        "returning id, name, description, publication_status, suggest_new_fields, created_at, updated_at",
        *params,
    )
    return dict(row)


async def delete_dashboard(conn, org_id, user: dict, dashboard_id: str) -> None:
    """Удаление дашборда целиком — пока он не «в работе».

    Страницы, виджеты, версии, заявки на публикацию, гранты доступа, избранное,
    пресеты фильтров и комментарии уходят каскадом. Слепки архива НЕ теряются:
    `dashboard_archives.dashboard_id` объявлен `on delete set null`, снимок
    данных живёт в jsonb и переживает удаление исходного дашборда — так и было
    задумано (архив на то и архив).

    Три стоп-фактора: опубликован, отправлен на проверку, входит в витрину.
    Все три означают, что дашборд кто-то видит прямо сейчас, — молча убирать
    его из-под пользователей нельзя, поэтому объясняем, что сделать сначала.

    Право на удаление — только у роли superadmin (см. проверку ниже).
    """
    d = await conn.fetchrow(
        "select name, publication_status, created_by from dashboards "
        "where id=$1::uuid and organization_id=$2", dashboard_id, org_id)
    if d is None:
        raise DashboardError("Дашборд не найден")

    # Удаляет только суперадминистратор — решение заказчика (11.08.2026).
    # Остальным доступны обратимые действия: снять с публикации, отправить
    # в архив. Проверка продублирована здесь, а не только в зависимости
    # роутера, чтобы правило держалось и при вызове сервиса из другого места.
    roles = set(user.get("roles") or ())
    if "superadmin" not in roles:
        raise DashboardError("Недостаточно прав: удалить дашборд может только суперадминистратор")

    if d["publication_status"] == "published":
        raise DashboardError("Дашборд опубликован — удаление отменено. Сначала снимите его с публикации.")
    if d["publication_status"] == "review":
        raise DashboardError("Дашборд отправлен на проверку — удаление отменено. Сначала отзовите заявку.")

    shows = await conn.fetch(
        "select s.name from showcase_items i join showcases s on s.id=i.showcase_id "
        "where i.dashboard_id=$1::uuid order by s.name", dashboard_id)
    if shows:
        names = ", ".join(f"«{r['name']}»" for r in shows)
        raise DashboardError(
            f"Дашборд входит в витрины ({names}) — удаление отменено. Сначала уберите его оттуда.")

    async with conn.transaction():
        # securable_objects связан с дашбордом и виджетами ЛОГИЧЕСКИМ ключом
        # (FK нет) — каскад его не заберёт, чистим сами; привязанные object_acl
        # уйдут каскадом от securable_objects.
        await conn.execute(
            "delete from securable_objects where (object_type='dashboard' and object_id=$1::uuid) "
            "or (object_type='widget' and object_id in (select id from widgets where dashboard_id=$1::uuid))",
            dashboard_id)
        # Уведомления по дашборду тоже без FK — адресаты уйдут каскадом от события.
        await conn.execute(
            "delete from notification_events where entity_type='dashboard' and entity_id=$1::uuid",
            dashboard_id)
        # Запись в журнал аудита сделает триггер trg_audit_dashboards (актор — из
        # GUC app.current_user_id, её проставляет db.acquire(user_id)); вручную
        # событие не пишем, иначе в журнале будет дубль.
        await conn.execute("delete from dashboards where id=$1::uuid", dashboard_id)


# --------------------------------------------------------------------------- #
# Страницы
# --------------------------------------------------------------------------- #
async def create_page(conn, org_id, user_id, dashboard_id: str, name: str,
                      description: Optional[str], layout_mode: str = "grid",
                      period: Optional[str] = None) -> dict:
    """`period` — отчётная дата страницы-среза (виджеты закреплены за ней)."""
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    await _assert_editable(conn, dashboard_id)
    if await conn.fetchval("select 1 from dashboard_pages where dashboard_id=$1::uuid and name=$2", dashboard_id, name):
        raise DashboardError("Страница с таким именем уже есть")
    pos = await conn.fetchval(
        "select coalesce(max(position),-1)+1 from dashboard_pages where dashboard_id=$1::uuid", dashboard_id)
    row = await conn.fetchrow(
        "insert into dashboard_pages(dashboard_id, name, description, position, created_by, layout_mode, period) "
        "values($1::uuid,$2,$3,$4,$5,$6,$7::text::date) "
        "returning id, name, description, position, layout_mode, period",
        dashboard_id, name, description, pos, user_id, layout_mode, period,
    )
    return dict(row)


async def update_page(conn, org_id, page_id: str, name: Optional[str], description: Optional[str],
                      layout_mode: Optional[str] = None) -> dict:
    p = await _page_org(conn, org_id, page_id)
    if p is None:
        raise DashboardError("Страница не найдена")
    await _assert_editable(conn, p["dashboard_id"])
    if layout_mode is not None and layout_mode not in LAYOUT_MODES:
        raise DashboardError(f"Неизвестный режим раскладки: {layout_mode}")
    row = await conn.fetchrow(
        "update dashboard_pages set name=coalesce($2,name), description=coalesce($3,description), "
        "layout_mode=coalesce($4,layout_mode), "
        "updated_at=now() where id=$1::uuid returning id, name, description, position, layout_mode, period",
        page_id, name, description, layout_mode,
    )
    return dict(row)


async def delete_page(conn, org_id, page_id: str) -> None:
    p = await _page_org(conn, org_id, page_id)
    if p is None:
        raise DashboardError("Страница не найдена")
    await _assert_editable(conn, p["dashboard_id"])
    await conn.execute("delete from dashboard_pages where id=$1::uuid", page_id)


async def list_page_widgets(conn, org_id, page_id: str, user: dict) -> dict:
    p = await _page_org(conn, org_id, page_id)
    if p is None:
        raise DashboardError("Страница не найдена")
    if not await _can_view(conn, org_id, user, str(p["dashboard_id"])):
        raise DashboardError("Страница не найдена")
    allowed = await visible_widget_ids(conn, org_id, user, str(p["dashboard_id"]))
    rows = await conn.fetch(
        "select id, name, widget_type, position_x, position_y, width, height, config "
        "from widgets where page_id=$1::uuid order by position_y, position_x", page_id,
    )
    if allowed is not None:
        rows = [w for w in rows if str(w["id"]) in allowed]
    # Пояснение «что это за цифра» считаем ЗДЕСЬ, пачкой на всю страницу:
    # значок ⓘ должен отвечать сразу при наведении, а догрузка по одному
    # значку показала бы пустоту ровно в тот момент, когда на неё смотрят.
    explain = await explain_widgets(conn, org_id, widget_configs(rows))
    return {"page_id": page_id, "widgets": [
        {**{k: w[k] for k in ("id", "name", "widget_type", "position_x", "position_y", "width", "height")},
         "config": _cfg(w), "explain": explain.get(str(w["id"]))} for w in rows]}


# --------------------------------------------------------------------------- #
# Виджеты
# --------------------------------------------------------------------------- #
async def create_widget(conn, org_id, user_id, page_id: str, name: str, widget_type: str,
                        config: dict, pos: dict) -> dict:
    if widget_type not in WIDGET_TYPES:
        raise DashboardError(f"Неизвестный тип виджета: {widget_type}")
    p = await _page_org(conn, org_id, page_id)
    if p is None:
        raise DashboardError("Страница не найдена")
    await _assert_editable(conn, p["dashboard_id"])
    config = apply_default_alerts(widget_type, config or {})
    row = await conn.fetchrow(
        "insert into widgets(organization_id, dashboard_id, page_id, name, widget_type, "
        "position_x, position_y, width, height, config, created_by) "
        "values($1,$2,$3::uuid,$4,$5,$6,$7,$8,$9,$10::jsonb,$11) returning id",
        org_id, p["dashboard_id"], page_id, name, widget_type,
        pos.get("position_x", 0), pos.get("position_y", 0), pos.get("width", 4), pos.get("height", 3),
        json.dumps(config, ensure_ascii=False), user_id,
    )
    return {"id": str(row["id"]), "widget_type": widget_type}




async def update_widget(conn, org_id, widget_id: str, patch: dict) -> dict:
    w = await _widget_org(conn, org_id, widget_id)
    if w is None:
        raise DashboardError("Виджет не найден")
    await _assert_editable(conn, w["dashboard_id"])
    wtype = patch.get("widget_type")
    if wtype is not None and wtype not in WIDGET_TYPES:
        raise DashboardError(f"Неизвестный тип виджета: {wtype}")
    new_cfg = apply_default_alerts(wtype or w["widget_type"], patch["config"]) if "config" in patch else None
    cfg = json.dumps(new_cfg, ensure_ascii=False) if new_cfg is not None else None
    row = await conn.fetchrow(
        "update widgets set name=coalesce($2,name), widget_type=coalesce($8,widget_type), "
        "position_x=coalesce($3,position_x), position_y=coalesce($4,position_y), "
        "width=coalesce($5,width), height=coalesce($6,height), "
        "config=coalesce($7::jsonb,config), updated_at=now() where id=$1::uuid returning id",
        widget_id, patch.get("name"), patch.get("position_x"), patch.get("position_y"),
        patch.get("width"), patch.get("height"), cfg, wtype,
    )
    await cache.delete_prefix(f"wd:{widget_id}:")  # инвалидируем кэш данных виджета
    return {"id": str(row["id"])}


async def fit_page_layout(conn, org_id, page_id: str) -> dict:
    """Подогнать размеры виджетов страницы под их тип.

    Дашборды, собранные до перехода авто-сборки на крупные карточки, держат
    виджеты 3×3: имя показателя обрезается до «Колич обращ за…», а число не
    помещается вместе с шапкой. Растягивать полтора десятка карточек мышью по
    одной — занятие на полчаса, поэтому та же раскладка, что у авто-сборки,
    применяется одной кнопкой. Состав страницы НЕ меняется: ни один виджет не
    добавляется и не удаляется — двигаются только размер и место.
    """
    p = await _page_org(conn, org_id, page_id)
    if p is None:
        raise DashboardError("Страница не найдена")
    await _assert_editable(conn, p["dashboard_id"])
    # config нужен, потому что у матрицы высота зависит от СОДЕРЖИМОГО (числа
    # показателей), а не только от типа: без него подгонка ужимала бы её
    # обратно до табличного размера и ломала то, что собрал мастер.
    rows = await conn.fetch(
        "select id, widget_type, config, position_x, position_y, width, height from widgets "
        "where page_id=$1::uuid order by position_y, position_x", page_id)
    if not rows:
        raise DashboardError("На странице нет виджетов")
    changed = 0
    for spec in fit_layout([dict(r) for r in rows]):
        was = next(r for r in rows if str(r["id"]) == spec["id"])
        if (was["position_x"], was["position_y"], was["width"], was["height"]) == (
                spec["position_x"], spec["position_y"], spec["width"], spec["height"]):
            continue
        await conn.execute(
            "update widgets set position_x=$2, position_y=$3, width=$4, height=$5, updated_at=now() "
            "where id=$1::uuid",
            spec["id"], spec["position_x"], spec["position_y"], spec["width"], spec["height"])
        changed += 1
    return {"widgets": len(rows), "changed": changed}


async def delete_widget(conn, org_id, widget_id: str) -> None:
    w = await _widget_org(conn, org_id, widget_id)
    if w is None:
        raise DashboardError("Виджет не найден")
    await _assert_editable(conn, w["dashboard_id"])
    await conn.execute("delete from widgets where id=$1::uuid", widget_id)
    await cache.delete_prefix(f"wd:{widget_id}:")


# --------------------------------------------------------------------------- #
# Управление доступом к дашборду (гранты)
# --------------------------------------------------------------------------- #
async def grant_targets(conn, org_id) -> dict:
    """Кому можно выдать доступ: пользователи и роли организации."""
    users = await conn.fetch(
        "select id, login, full_name from users where organization_id=$1 and is_active order by login", org_id)
    roles = await conn.fetch(
        "select id, code, name from roles where organization_id=$1 order by name", org_id)
    return {
        "users": [{"id": str(u["id"]), "login": u["login"], "full_name": u["full_name"]} for u in users],
        "roles": [{"id": str(r["id"]), "code": r["code"], "name": r["name"]} for r in roles],
    }


async def list_grants(conn, org_id, dashboard_id: str) -> List[dict]:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    rows = await conn.fetch(
        "select g.id, g.scope, g.grantee_type, g.role_id, g.user_id, g.widget_id, g.granted_at, "
        "r.name as role_name, r.code as role_code, u.login, u.full_name, w.name as widget_name "
        "from access_grants g "
        "left join roles r on r.id=g.role_id left join users u on u.id=g.user_id "
        "left join widgets w on w.id=g.widget_id "
        "where g.dashboard_id=$1::uuid order by g.scope, g.granted_at", dashboard_id)
    out = []
    for g in rows:
        label = (g["role_name"] or g["role_code"]) if g["grantee_type"] == "role" else (g["full_name"] or g["login"])
        out.append({"id": str(g["id"]), "scope": g["scope"], "grantee_type": g["grantee_type"],
                    "role_id": str(g["role_id"]) if g["role_id"] else None,
                    "user_id": str(g["user_id"]) if g["user_id"] else None,
                    "widget_id": str(g["widget_id"]) if g["widget_id"] else None,
                    "widget_name": g["widget_name"], "label": label, "granted_at": g["granted_at"]})
    return out


async def dashboard_widgets_flat(conn, org_id, dashboard_id: str) -> List[dict]:
    """Плоский список виджетов дашборда (для выбора при выдаче widget-гранта)."""
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    rows = await conn.fetch(
        "select w.id, w.name, w.widget_type, p.name as page_title "
        "from widgets w join dashboard_pages p on p.id=w.page_id "
        "where w.dashboard_id=$1::uuid order by p.position, w.position_y, w.position_x", dashboard_id)
    return [{"id": str(w["id"]), "name": w["name"], "widget_type": w["widget_type"],
             "page_title": w["page_title"]} for w in rows]


async def add_grant(conn, org_id, granted_by, dashboard_id: str, grantee_type: str,
                    role_id: Optional[str], user_id: Optional[str],
                    scope: str = "dashboard", widget_id: Optional[str] = None) -> dict:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    if scope not in ("dashboard", "widget"):
        raise DashboardError("scope должен быть 'dashboard' или 'widget'")
    if grantee_type not in ("role", "user"):
        raise DashboardError("grantee_type должен быть 'role' или 'user'")
    if scope == "widget":
        if not widget_id:
            raise DashboardError("Укажите виджет")
        # виджет должен принадлежать этому дашборду и организации
        if not await conn.fetchval(
                "select 1 from widgets where id=$1::uuid and dashboard_id=$2::uuid and organization_id=$3",
                widget_id, dashboard_id, org_id):
            raise DashboardError("Виджет не найден в этом дашборде")
    else:
        widget_id = None
    # условие совпадения виджета в проверке дубликата (NULL != NULL в SQL → is not distinct from)
    wcond = "widget_id is not distinct from $3::uuid"
    if grantee_type == "role":
        if not role_id:
            raise DashboardError("Укажите роль")
        if not await conn.fetchval("select 1 from roles where id=$1::uuid and organization_id=$2", role_id, org_id):
            raise DashboardError("Роль не найдена")
        user_id = None
        exists = await conn.fetchval(
            f"select 1 from access_grants where dashboard_id=$1::uuid and scope=$2 and {wcond} "
            "and grantee_type='role' and role_id=$4::uuid", dashboard_id, scope, widget_id, role_id)
    else:
        if not user_id:
            raise DashboardError("Укажите пользователя")
        if not await conn.fetchval("select 1 from users where id=$1::uuid and organization_id=$2", user_id, org_id):
            raise DashboardError("Пользователь не найден")
        role_id = None
        exists = await conn.fetchval(
            f"select 1 from access_grants where dashboard_id=$1::uuid and scope=$2 and {wcond} "
            "and grantee_type='user' and user_id=$4::uuid", dashboard_id, scope, widget_id, user_id)
    if exists:
        raise DashboardError("Доступ уже выдан")
    row = await conn.fetchrow(
        "insert into access_grants(scope, dashboard_id, widget_id, grantee_type, role_id, user_id, granted_by) "
        "values($1, $2::uuid, $3::uuid, $4, $5::uuid, $6::uuid, $7) returning id",
        scope, dashboard_id, widget_id, grantee_type, role_id, user_id, granted_by)
    await audit_svc.write_event(
        conn, org_id, granted_by, "grant_access", "dashboard", dashboard_id,
        new_data={"grant_id": str(row["id"]), "scope": scope, "widget_id": widget_id,
                  "grantee_type": grantee_type, "role_id": role_id, "user_id": user_id})
    return {"id": str(row["id"])}


async def remove_grant(conn, org_id, dashboard_id: str, grant_id: str, actor_user_id) -> None:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    old = await conn.fetchrow(
        "select grantee_type, role_id, user_id from access_grants "
        "where id=$1::uuid and dashboard_id=$2::uuid",
        grant_id, dashboard_id)
    if old is None:
        raise DashboardError("Грант не найден")
    await conn.execute(
        "delete from access_grants where id=$1::uuid and dashboard_id=$2::uuid",
        grant_id, dashboard_id)
    await audit_svc.write_event(
        conn, org_id, actor_user_id, "revoke_access", "dashboard", dashboard_id,
        old_data={"grant_id": grant_id, "grantee_type": old["grantee_type"],
                  "role_id": str(old["role_id"]) if old["role_id"] else None,
                  "user_id": str(old["user_id"]) if old["user_id"] else None})


# --------------------------------------------------------------------------- #
# Пресеты фильтров дашборда (FR-13, сохранённые наборы)
# filters = {from, to, row} — период и категория/строка глобального фильтра.
# Список/применение — по праву просмотра; создание/удаление — manage.
# --------------------------------------------------------------------------- #
_PRESET_KEYS = ("from", "to", "row")


async def list_presets(conn, org_id, user: dict, dashboard_id: str) -> List[dict]:
    if not await _can_view(conn, org_id, user, dashboard_id):
        raise DashboardError("Дашборд не найден")
    rows = await conn.fetch(
        "select id, name, filters, created_at from dashboard_filter_presets "
        "where dashboard_id=$1::uuid order by name", dashboard_id)
    out = []
    for r in rows:
        f = r["filters"]
        if isinstance(f, str):
            f = json.loads(f)
        out.append({"id": str(r["id"]), "name": r["name"], "filters": f or {}})
    return out


async def create_preset(conn, org_id, user_id, dashboard_id: str, name: str, filters: dict) -> dict:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    name = (name or "").strip()
    if not name:
        raise DashboardError("Укажите название пресета")
    clean = {k: filters[k] for k in _PRESET_KEYS if filters.get(k)}
    if await conn.fetchval(
            "select 1 from dashboard_filter_presets where dashboard_id=$1::uuid and name=$2", dashboard_id, name):
        raise DashboardError("Пресет с таким именем уже есть")
    row = await conn.fetchrow(
        "insert into dashboard_filter_presets(dashboard_id, name, filters, created_by) "
        "values($1::uuid,$2,$3::jsonb,$4) returning id, name",
        dashboard_id, name, json.dumps(clean, ensure_ascii=False), user_id)
    return {"id": str(row["id"]), "name": row["name"], "filters": clean}


async def delete_preset(conn, org_id, dashboard_id: str, preset_id: str) -> None:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    res = await conn.execute(
        "delete from dashboard_filter_presets where id=$1::uuid and dashboard_id=$2::uuid",
        preset_id, dashboard_id)
    if res.endswith("0"):
        raise DashboardError("Пресет не найден")



# --------------------------------------------------------------------------- #
# Версии и публикация дашборда
# --------------------------------------------------------------------------- #
async def _snapshot(conn, dashboard_id: str) -> dict:
    pages = await conn.fetch(
        "select id, name, description, position, layout_mode, period from dashboard_pages "
        "where dashboard_id=$1::uuid order by position", dashboard_id)
    out = []
    for p in pages:
        ws = await conn.fetch(
            "select name, widget_type, position_x, position_y, width, height, config "
            "from widgets where page_id=$1 order by position_y, position_x", p["id"])
        out.append({"name": p["name"], "description": p["description"], "position": p["position"],
                    "layout_mode": p["layout_mode"],
                    "period": p["period"].isoformat() if p["period"] else None,
                    "widgets": [{"name": w["name"], "widget_type": w["widget_type"],
                                 "position_x": w["position_x"], "position_y": w["position_y"],
                                 "width": w["width"], "height": w["height"], "config": _cfg(w)} for w in ws]})
    return {"pages": out}


async def publish(conn, org_id, user_id, dashboard_id: str) -> dict:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    snap = await _snapshot(conn, dashboard_id)
    vno = await conn.fetchval(
        "select coalesce(max(version_no),0)+1 from dashboard_versions where dashboard_id=$1::uuid", dashboard_id)
    await conn.execute(
        "insert into dashboard_versions(dashboard_id, version_no, snapshot, created_by, status_code) "
        "values($1::uuid,$2,$3::jsonb,$4,'published')", dashboard_id, vno,
        json.dumps(snap, ensure_ascii=False), user_id)
    await conn.execute(
        "update dashboards set publication_status='published', published_by=$2, published_at=now(), "
        "version_no=$3, updated_at=now() where id=$1::uuid", dashboard_id, user_id, vno)
    # Прямая публикация админом (override) закрывает висящую заявку на проверку.
    # Иначе заявка навсегда остаётся в очереди модератора и в /reports/moderation
    # как pending, а последующее «Одобрить» откатило бы дашборд на версию,
    # зафиксированную в момент отправки на проверку (перезапись version_no).
    closed = await conn.fetchval(
        "with upd as (update publication_requests set status='cancelled', resolved_at=now() "
        "where dashboard_id=$1::uuid and status='pending_moderation' returning 1) "
        "select count(*) from upd", dashboard_id)
    await audit_svc.write_event(
        conn, org_id, user_id, "publish", "dashboard", dashboard_id,
        new_data={"version_no": vno, "publication_status": "published",
                  **({"review_request_cancelled": True} if closed else {})})
    return {"publication_status": "published", "version_no": vno}


async def unpublish(conn, org_id, dashboard_id: str) -> dict:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    await conn.execute(
        "update dashboards set publication_status='draft', updated_at=now() where id=$1::uuid", dashboard_id)
    return {"publication_status": "draft"}


async def list_versions(conn, org_id, user: dict, dashboard_id: str) -> list:
    if not await _can_view(conn, org_id, user, dashboard_id):
        raise DashboardError("Дашборд не найден")
    rows = await conn.fetch(
        "select version_no, status_code, created_at from dashboard_versions "
        "where dashboard_id=$1::uuid order by version_no desc", dashboard_id)
    return [dict(r) for r in rows]


async def restore_version(conn, org_id, user_id, dashboard_id: str, version_no: int) -> dict:
    if not await _owns_dashboard(conn, org_id, dashboard_id):
        raise DashboardError("Дашборд не найден")
    snap = await conn.fetchval(
        "select snapshot from dashboard_versions where dashboard_id=$1::uuid and version_no=$2",
        dashboard_id, version_no)
    if snap is None:
        raise DashboardError("Версия не найдена")
    if isinstance(snap, str):
        snap = json.loads(snap)
    await conn.execute("delete from dashboard_pages where dashboard_id=$1::uuid", dashboard_id)
    for page in snap.get("pages", []):
        p = await create_page(conn, org_id, user_id, dashboard_id, page["name"], page.get("description"),
                              page.get("layout_mode") or "grid", page.get("period"))
        for w in page.get("widgets", []):
            await create_widget(conn, org_id, user_id, str(p["id"]), w["name"], w["widget_type"], w.get("config", {}),
                                {"position_x": w.get("position_x", 0), "position_y": w.get("position_y", 0),
                                 "width": w.get("width", 4), "height": w.get("height", 4)})
    return {"restored_version": version_no, "pages": len(snap.get("pages", []))}
