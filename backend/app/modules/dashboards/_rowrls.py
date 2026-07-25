"""Row-level RLS: видимость строк данных (row_label) по подразделению.

Opt-in на объект (миграция 024): пока для объекта нет правил data_row_acl —
строки видят все. Как только правило появилось — непривилегированный видит
только строки, выданные его подразделению. Привилегированные и предпросмотр
(user=None) видят все строки.

Применяется к ВИДЖЕТНЫМ чтениям датасета; именованные метрики не фильтруются.
Лист-модуль (через conn).
"""
from __future__ import annotations

from typing import List, Optional

from ... import cache
from ._base import DashboardError
from ._rls import _user_ctx


async def object_has_row_acl(conn, object_id) -> bool:
    return bool(await conn.fetchval(
        "select 1 from data_row_acl where object_id=$1::uuid limit 1", object_id))


async def _object_of_dataset(conn, org_id, dataset_code: str):
    return await conn.fetchval(
        "select object_id from dataset_releases where organization_id=$1 and code=$2 limit 1",
        org_id, dataset_code)


async def allowed_rows_for_dataset(conn, org_id, user: Optional[dict], dataset_code: str) -> Optional[set]:
    """None — без ограничения (видны все строки); set — whitelist row_label
    (возможно пустой → пользователь не видит строк). user=None (предпросмотр) и
    привилегированные роли → None."""
    if user is None:
        return None
    ctx = await _user_ctx(conn, user)
    if ctx["privileged"]:
        return None
    obj = await _object_of_dataset(conn, org_id, dataset_code)
    if obj is None or not await object_has_row_acl(conn, obj):
        return None
    dept = await conn.fetchval("select department_id from users where id=$1", user["id"])
    if not dept:
        return set()  # RLS включён у объекта, а у пользователя нет отдела → fail closed
    rows = await conn.fetch(
        "select row_label from data_row_acl where object_id=$1 and department_id=$2", obj, dept)
    return {r["row_label"] for r in rows}


async def rls_tag(conn, user: Optional[dict]) -> str:
    """Метка для ключа кэша данных виджета: у привилегированных/предпросмотра —
    общий 'all'; иначе — по подразделению (данные строк у разных отделов разные)."""
    if user is None:
        return "all"
    ctx = await _user_ctx(conn, user)
    if ctx["privileged"]:
        return "all"
    dept = await conn.fetchval("select department_id from users where id=$1", user["id"])
    return f"d:{dept}" if dept else "d:none"


# --------------------------------------------------------------------------- #
# Управление правилами (admin/moderator)
# --------------------------------------------------------------------------- #
async def _object_in_org(conn, org_id, object_id: str) -> bool:
    return bool(await conn.fetchval(
        "select 1 from objects where id=$1::uuid and organization_id=$2", object_id, org_id))


async def get_row_acl(conn, org_id, object_id: str) -> dict:
    """Данные для редактора: доступные строки объекта, подразделения, текущие правила."""
    if not await _object_in_org(conn, org_id, object_id):
        raise DashboardError("Объект не найден")
    labels = await conn.fetch(
        "select distinct dv.row_label from dataset_values dv "
        "join dataset_releases dr on dr.id=dv.dataset_release_id "
        "where dr.object_id=$1::uuid and dv.row_label is not null order by dv.row_label", object_id)
    deps = await conn.fetch(
        "select id, name from departments where organization_id=$1 order by name", org_id)
    rules = await conn.fetch(
        "select department_id, row_label from data_row_acl where object_id=$1::uuid", object_id)
    by_dep: dict = {}
    for r in rules:
        by_dep.setdefault(str(r["department_id"]), []).append(r["row_label"])
    return {
        "enabled": len(rules) > 0,
        "row_labels": [r["row_label"] for r in labels],
        "departments": [{"id": str(d["id"]), "name": d["name"],
                         "row_labels": by_dep.get(str(d["id"]), [])} for d in deps],
    }


async def set_row_acl(conn, org_id, actor_user_id, object_id: str,
                      department_id: str, row_labels: List[str]) -> dict:
    """Заменить набор разрешённых строк для подразделения в объекте (whitelist)."""
    if not await _object_in_org(conn, org_id, object_id):
        raise DashboardError("Объект не найден")
    if not await conn.fetchval(
            "select 1 from departments where id=$1::uuid and organization_id=$2", department_id, org_id):
        raise DashboardError("Подразделение не найдено")
    labels = sorted({(s or "").strip() for s in row_labels if (s or "").strip()})
    async with conn.transaction():
        await conn.execute(
            "delete from data_row_acl where object_id=$1::uuid and department_id=$2::uuid",
            object_id, department_id)
        for lbl in labels:
            await conn.execute(
                "insert into data_row_acl(object_id, department_id, row_label, created_by) "
                "values($1::uuid, $2::uuid, $3, $4)", object_id, department_id, lbl, actor_user_id)
    # Правила видимости строк изменились → сбрасываем кэш данных виджетов
    # (ключи учитывают подразделение; какие именно виджеты затронуты — точечно
    # не вычислить, поэтому чистим весь префикс; смена правил — редкое админ-действие).
    await cache.delete_prefix("wd:")
    return {"object_id": object_id, "department_id": department_id, "row_labels": labels}
