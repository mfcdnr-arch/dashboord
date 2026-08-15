"""Сервис модерации дашбордов.

Жизненный цикл (dashboards.publication_status): draft → review → published,
либо review → draft (возврат на доработку). Одна ступень: одобрение модератора
= публикация. Конфликт интересов: одобрять/публиковать собственный дашборд
(автор или инициатор заявки) нельзя — исключение только для superadmin, и такое
самоодобрение помечается в аудите (self_approved). Наполняет publication_requests /
publication_reviews / moderation_session / moderation_check_result.
"""
from __future__ import annotations

import json
from typing import Optional

from ..audit import service as audit_svc
from ..notifications import service as notif

# 6 блоков чек-листа проверки (совпадают с moderation_check_result.check_block).
CHECK_BLOCKS = ["structure", "data", "metrics", "filters", "access", "visual"]
CHECK_STATUSES = {"idle", "passed", "warning", "failed", "skipped"}
BLOCK_LABELS = {
    "structure": "Структура", "data": "Данные", "metrics": "Метрики",
    "filters": "Фильтры", "access": "Доступ", "visual": "Визуализация",
}
# Роли, которые могут модерировать (одобрять/возвращать/публиковать).
MODERATOR_ROLES = {"superadmin", "admin", "moderator", "senior_moderator"}
# Роль, которой разрешено одобрять собственную работу: владелец системы должен
# уметь пройти цикл в одиночку, когда второго сотрудника ещё нет.
SELF_APPROVE_ROLE = "superadmin"


class ModerationError(Exception):
    """Доменная ошибка модерации."""


async def _load_roles(conn, user: dict) -> set:
    """Роли пользователя. get_current_user их не кладёт (в отличие от
    require_roles), поэтому при отсутствии — подгружаем из БД."""
    if user.get("roles") is not None:
        return set(user["roles"])
    rows = await conn.fetch(
        "select r.code from user_roles ur join roles r on r.id=ur.role_id where ur.user_id=$1", user["id"])
    return {r["code"] for r in rows}


async def _dashboard(conn, org_id, dashboard_id: str) -> dict:
    row = await conn.fetchrow(
        "select id, name, publication_status, created_by from dashboards "
        "where id=$1::uuid and organization_id=$2", dashboard_id, org_id)
    if row is None:
        raise ModerationError("Дашборд не найден")
    return dict(row)


async def _pending_request(conn, dashboard_id: str) -> Optional[dict]:
    row = await conn.fetchrow(
        "select id, dashboard_version_id, requested_by, requested_at from publication_requests "
        "where dashboard_id=$1::uuid and status='pending_moderation' order by requested_at desc limit 1",
        dashboard_id)
    return dict(row) if row else None


async def list_reason_codes(conn) -> list:
    """Причины возврата на доработку (действие request_changes) + OTHER."""
    rows = await conn.fetch(
        "select code, label_ru, severity from moderation_reason_code "
        "where applicable_action like '%request_changes%' order by "
        "case severity when 'critical' then 0 when 'high' then 1 when 'medium' then 2 else 3 end, label_ru")
    return [{"code": r["code"], "label": r["label_ru"], "severity": r["severity"]} for r in rows]


async def submit_for_review(conn, org_id, user: dict, dashboard_id: str) -> dict:
    """Отправить дашборд на проверку: снимок версии + заявка pending_moderation."""
    from ..dashboards import service as dsvc

    d = await _dashboard(conn, org_id, dashboard_id)
    roles = await _load_roles(conn, user)
    if not (roles & MODERATOR_ROLES) and d["created_by"] != user["id"]:
        raise ModerationError("Отправить на проверку может автор дашборда или модератор")
    if d["publication_status"] == "review":
        raise ModerationError("Дашборд уже на проверке")
    if d["publication_status"] == "published":
        raise ModerationError("Дашборд уже опубликован; снимите с публикации перед новой проверкой")

    snap = await dsvc._snapshot(conn, dashboard_id)
    vno = await conn.fetchval(
        "select coalesce(max(version_no),0)+1 from dashboard_versions where dashboard_id=$1::uuid", dashboard_id)
    version_id = await conn.fetchval(
        "insert into dashboard_versions(dashboard_id, version_no, snapshot, created_by, status_code) "
        "values($1::uuid,$2,$3::jsonb,$4,'ready_for_review') returning id",
        dashboard_id, vno, json.dumps(snap, ensure_ascii=False), user["id"])
    await conn.execute(
        "insert into publication_requests(dashboard_id, dashboard_version_id, status, requested_by, requested_at) "
        "values($1::uuid,$2,'pending_moderation',$3,now())", dashboard_id, version_id, user["id"])
    await conn.execute(
        "update dashboards set publication_status='review', updated_at=now() where id=$1::uuid", dashboard_id)

    # Заявка лежала в очереди, пока модератор сам туда не заглянет: счётчик на
    # «Главной» был, а уведомления — нет. Автору сообщать незачем, он и отправил.
    recipients = [uid for uid in await notif.management_user_ids(conn, org_id) if uid != user["id"]]
    await notif.notify(
        conn, org_id, "dashboard.review_requested", "dashboard", dashboard_id,
        {"dashboard_name": d["name"], "author": user.get("full_name") or user.get("login") or "",
         "version_no": vno},
        recipients)
    return {"publication_status": "review", "version_no": vno}


async def cancel_review(conn, org_id, user: dict, dashboard_id: str) -> dict:
    """Отозвать заявку на проверку (инициатор или админ) → назад в черновик."""
    await _dashboard(conn, org_id, dashboard_id)
    req = await _pending_request(conn, dashboard_id)
    if req is None:
        raise ModerationError("Активной заявки на проверку нет")
    roles = await _load_roles(conn, user)
    if req["requested_by"] != user["id"] and "admin" not in roles:
        raise ModerationError("Отозвать заявку может только инициатор или администратор")
    await conn.execute(
        "update publication_requests set status='cancelled', resolved_at=now() where id=$1", req["id"])
    await conn.execute(
        "update dashboards set publication_status='draft', updated_at=now() where id=$1::uuid", dashboard_id)
    return {"publication_status": "draft"}


async def queue(conn, org_id, user: dict) -> list:
    """Очередь заявок на модерации (для модераторов). own=собственный дашборд,
    can_approve=можно ли его одобрить (свой — только суперадмину)."""
    rows = await conn.fetch(
        "select pr.dashboard_id, d.name, pr.requested_at, pr.requested_by, "
        "u.login as requester_login, u.full_name as requester_name, d.created_by "
        "from publication_requests pr "
        "join dashboards d on d.id=pr.dashboard_id "
        "left join users u on u.id=pr.requested_by "
        "where pr.status='pending_moderation' and d.organization_id=$1 "
        "order by pr.requested_at", org_id)
    roles = await _load_roles(conn, user)
    may_self = SELF_APPROVE_ROLE in roles
    out = []
    for r in rows:
        own = r["requested_by"] == user["id"] or r["created_by"] == user["id"]
        out.append({
            "dashboard_id": str(r["dashboard_id"]), "name": r["name"],
            "requested_at": r["requested_at"],
            "requester": r["requester_name"] or r["requester_login"] or "—",
            "own": own,
            "can_approve": (not own) or may_self,
        })
    return out


async def _save_checklist(conn, session_id, checklist: Optional[dict]) -> None:
    if not checklist:
        return
    for block in CHECK_BLOCKS:
        status = checklist.get(block, "idle")
        if status not in CHECK_STATUSES:
            status = "idle"
        await conn.execute(
            "insert into moderation_check_result(moderation_session_id, check_block, status) "
            "values($1,$2,$3)", session_id, block, status)


async def decide(conn, org_id, user: dict, dashboard_id: str, decision: str,
                 reason_code: Optional[str] = None, comment: Optional[str] = None,
                 checklist: Optional[dict] = None) -> dict:
    """Решение модератора: approve (→ публикация) или return (→ доработка)."""
    roles = await _load_roles(conn, user)
    if not (roles & MODERATOR_ROLES):
        raise ModerationError("Модерация доступна модератору или администратору")
    if decision not in ("approve", "return"):
        raise ModerationError("decision должен быть 'approve' или 'return'")

    d = await _dashboard(conn, org_id, dashboard_id)
    req = await _pending_request(conn, dashboard_id)
    if req is None:
        raise ModerationError("Дашборд не находится на проверке")

    version_id = req["dashboard_version_id"]
    # moderation_session как якорь для чек-листа/лога
    session_id = await conn.fetchval(
        "insert into moderation_session(publication_request_id, dashboard_version_id, status_code, reviewer_id) "
        "values($1,$2,'completed',$3) returning id", req["id"], version_id, user["id"])
    await _save_checklist(conn, session_id, checklist)

    if decision == "approve":
        # Конфликт интересов: собственный дашборд одобряет только суперадмин
        # (владелец системы, работает в одиночку). Самоодобрение не замалчивается —
        # оно помечается в журнале аудита полем self_approved.
        own = req["requested_by"] == user["id"] or d["created_by"] == user["id"]
        if own and SELF_APPROVE_ROLE not in roles:
            raise ModerationError("Нельзя одобрять собственный дашборд (конфликт интересов) — нужен другой модератор")
        vno = await conn.fetchval(
            "select version_no from dashboard_versions where id=$1", version_id)
        await conn.execute("update dashboard_versions set status_code='published' where id=$1", version_id)
        await conn.execute(
            "update dashboards set publication_status='published', published_by=$2, published_at=now(), "
            "version_no=$3, updated_at=now() where id=$1::uuid", dashboard_id, user["id"], vno)
        await conn.execute(
            "update publication_requests set status='approved', resolved_at=now() where id=$1", req["id"])
        await conn.execute(
            "insert into publication_reviews(publication_request_id, reviewer_id, decision, comment) "
            "values($1,$2,'approved',$3)", req["id"], user["id"], comment)
        await audit_svc.write_event(
            conn, org_id, user["id"], "publish", "dashboard", dashboard_id,
            new_data={"version_no": vno, "via": "moderation", "publication_status": "published",
                      "self_approved": own})
        return {"decision": "approve", "publication_status": "published", "version_no": vno}

    # decision == 'return'
    if not reason_code:
        raise ModerationError("Для возврата на доработку укажите причину")
    ok = await conn.fetchval("select 1 from moderation_reason_code where code=$1", reason_code)
    if not ok:
        raise ModerationError("Неизвестная причина возврата")
    if reason_code == "OTHER" and not (comment and comment.strip()):
        raise ModerationError("Для причины «Иная» комментарий обязателен")
    full_comment = comment
    await conn.execute("update dashboard_versions set status_code='changes_requested' where id=$1", version_id)
    await conn.execute(
        "update dashboards set publication_status='draft', updated_at=now() where id=$1::uuid", dashboard_id)
    await conn.execute(
        "update publication_requests set status='returned_for_revision', resolved_at=now() where id=$1", req["id"])
    await conn.execute(
        "insert into publication_reviews(publication_request_id, reviewer_id, decision, comment) "
        "values($1,$2,'rejected',$3)", req["id"], user["id"],
        f"[{reason_code}] {full_comment or ''}".strip())
    return {"decision": "return", "publication_status": "draft", "reason_code": reason_code}


async def history(conn, org_id, dashboard_id: str) -> list:
    """История модерации дашборда: заявки + решения."""
    await _dashboard(conn, org_id, dashboard_id)
    rows = await conn.fetch(
        "select pr.status, pr.requested_at, pr.resolved_at, "
        "ur.login as requester, "
        "rv.decision, rv.comment, rv.created_at as decided_at, "
        "vr.login as reviewer "
        "from publication_requests pr "
        "left join users ur on ur.id=pr.requested_by "
        "left join publication_reviews rv on rv.publication_request_id=pr.id "
        "left join users vr on vr.id=rv.reviewer_id "
        "where pr.dashboard_id=$1::uuid order by pr.requested_at desc, rv.created_at desc", dashboard_id)
    return [{
        "status": r["status"], "requested_at": r["requested_at"], "resolved_at": r["resolved_at"],
        "requester": r["requester"], "decision": r["decision"], "comment": r["comment"],
        "decided_at": r["decided_at"], "reviewer": r["reviewer"],
    } for r in rows]
