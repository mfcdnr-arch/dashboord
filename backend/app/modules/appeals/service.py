"""Обращения пользователей к администратору/модератору (волна C).

Лёгкий тред: appeals (заявка, статус open→answered→closed) + appeal_messages
(сообщения обеих сторон). Один и тот же эндпоинт «добавить сообщение»
обслуживает и пользователя, и staff — роль определяется на лету по БД (роли
не всегда есть в user-словаре зависимости get_current_user).

Создание доступно и НЕАВТОРИЗОВАННО (create_appeal_by_login) — для
заблокированного аккаунта, который не может войти и получить обычный JWT.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from ..audit import service as audit_svc
from ..notifications import service as notif_svc

MAX_BODY = 4000
MAX_SUBJECT = 200
STAFF_ROLES = {"admin", "moderator", "senior_moderator", "superadmin"}

# Сколько НОВЫХ обращений один человек может завести за час. Ограничение
# появилось вместе с кнопкой «сообщить о проблеме» на виджете: раньше обращение
# заводили руками из «Кабинета» и десяток подряд был маловероятен, а теперь
# достаточно обойти страницу с двумя десятками виджетов.
#
# Ограничиваются только НОВЫЕ обращения. Ответ в уже открытом треде не считается
# — очередь администратора от него не растёт, а замолчать человека посреди
# разговора значит сломать сам разговор.
MAX_NEW_APPEALS_PER_HOUR = 10


class AppealsError(Exception):
    """Доменная ошибка модуля обращений."""


class AppealsRateLimited(AppealsError):
    """Слишком много новых обращений за час — отдаётся как 429, а не 400:
    это не ошибка ввода, а просьба подождать, и клиент должен их различать."""


async def _is_staff(conn, user_id) -> bool:
    rows = await conn.fetch(
        "select r.code from user_roles ur join roles r on r.id=ur.role_id where ur.user_id=$1", user_id)
    return bool({r["code"] for r in rows} & STAFF_ROLES)


def _clip(text: Optional[str], limit: int) -> Optional[str]:
    text = (text or "").strip()
    return text[:limit] if text else None


async def _assert_rate_ok(conn, user_id) -> None:
    """Потолок на новые обращения. Отказ называет, когда можно продолжить:
    «слишком часто» без срока читается как «сломалось» и заставляет жать ещё."""
    recent = await conn.fetch(
        "select created_at from appeals where user_id=$1 and created_at > now() - interval '1 hour' "
        "order by created_at", user_id)
    if len(recent) < MAX_NEW_APPEALS_PER_HOUR:
        return
    from datetime import timedelta, timezone
    free_at = recent[0]["created_at"] + timedelta(hours=1)
    mins = max(1, int((free_at - datetime.now(timezone.utc)).total_seconds() // 60) + 1)
    raise AppealsRateLimited(
        f"За последний час вы уже отправили {len(recent)} обращений. "
        f"Следующее можно будет отправить через {mins} мин. "
        f"Если это об одном и том же — допишите в уже открытое обращение, там переписка не ограничена.")


async def create_appeal(conn, org_id, user: dict, subject: Optional[str], body: str) -> dict:
    body = (body or "").strip()
    if not body:
        raise AppealsError("Пустое сообщение")
    if len(body) > MAX_BODY:
        raise AppealsError(f"Слишком длинное сообщение (максимум {MAX_BODY} символов)")
    await _assert_rate_ok(conn, user["id"])
    subject = _clip(subject, MAX_SUBJECT)
    row = await conn.fetchrow(
        "insert into appeals(organization_id, user_id, subject) values($1,$2,$3) returning id, created_at",
        org_id, user["id"], subject)
    await conn.execute(
        "insert into appeal_messages(appeal_id, sender_user_id, is_staff, body) values($1,$2,false,$3)",
        row["id"], user["id"], body)
    mgmt = [u for u in await notif_svc.management_user_ids(conn, org_id) if str(u) != str(user["id"])]
    if mgmt:
        await notif_svc.notify(
            conn, org_id, "appeal.created", "appeal", str(row["id"]),
            {"author": user.get("full_name") or user.get("login"), "subject": subject, "snippet": body[:140]},
            mgmt)
    await audit_svc.write_event(
        conn, org_id, user["id"], "create", "appeal", str(row["id"]),
        new_data={"subject": subject, "snippet": body[:200]})
    return {"id": str(row["id"]), "created_at": row["created_at"]}


async def create_access_request(conn, org_id, user: dict, wanted: str) -> dict:
    """«Мне нужен отчёт, которого я не вижу» (п. 15, последняя из трёх идей).

    **Списка недоступных отчётов человеку НЕ показываем — и не покажем.**
    Зритель видит только то, что ему открыто (`visible_dashboard_ids`), и это
    не техническое ограничение, а суть: даже одни названия говорят, какие
    показатели за кем закреплены. Кнопка «запросить доступ» рядом с серым
    недоступным отчётом раскрывала бы ровно то, что скрывает RLS.

    Поэтому запрос идёт ОТ ЧЕЛОВЕКА: он называет отчёт так, как ему его
    назвали (в письме, на совещании, от коллеги). Ценность не в списке, а в
    том, что запрос доходит одним нажатием и приходит с именем автора —
    администратору остаётся открыть его карточку доступа и отметить галочку.
    """
    wanted = (wanted or "").strip()
    if not wanted:
        raise AppealsError("Опишите, какой отчёт вам нужен")
    body = (
        f"{wanted}\n\n—— что нужно ——\n"
        f"Запрос доступа к отчёту. Сотрудник не видит его в своём списке.\n"
        f"Выдать доступ можно кнопкой ниже — откроется карточка доступа этого сотрудника."
    )
    created = await create_appeal(conn, org_id, user, "Запрос доступа к отчёту", body)
    await conn.execute(
        "update appeals set context=$2::jsonb where id=$1::uuid",
        created["id"], json.dumps({"kind": "access_request"}, ensure_ascii=False))
    return created


async def create_appeal_by_login(conn, login: str, body: str) -> None:
    """Заблокированный аккаунт: без JWT. Молчаливо ничего не делает, если логин
    не найден — ответ API одинаков в любом случае (не подтверждаем существование
    учётки посторонним)."""
    body = (body or "").strip()
    if not body:
        return
    body = body[:MAX_BODY]
    row = await conn.fetchrow(
        "select id, organization_id, full_name from users where login=$1", login)
    if row is None:
        return
    ap = await conn.fetchrow(
        "insert into appeals(organization_id, user_id, subject) values($1,$2,'Аккаунт заблокирован') returning id",
        row["organization_id"], row["id"])
    await conn.execute(
        "insert into appeal_messages(appeal_id, sender_user_id, is_staff, body) values($1,$2,false,$3)",
        ap["id"], row["id"], body)
    mgmt = await notif_svc.management_user_ids(conn, row["organization_id"])
    if mgmt:
        await notif_svc.notify(
            conn, row["organization_id"], "appeal.created", "appeal", str(ap["id"]),
            {"author": row["full_name"] or login, "subject": "Аккаунт заблокирован", "snippet": body[:140]},
            mgmt)
    # Актор — сам заблокированный пользователь (найден по логину); JWT у него
    # нет, но личность установлена достоверно (совпал логин).
    await audit_svc.write_event(
        conn, row["organization_id"], row["id"], "create", "appeal", str(ap["id"]),
        new_data={"subject": "Аккаунт заблокирован", "snippet": body[:200], "via": "blocked_login"})


def _waiting_hours(r) -> Optional[float]:
    """Сколько обращение ждёт ОТВЕТА. Считается только для открытых: у
    отвеченного и закрытого ожидание уже кончилось, и растущая цифра рядом с
    ними означала бы несуществующую проблему."""
    if r["status"] != "open":
        return None
    from datetime import timezone
    start = r["created_at"]
    return round((datetime.now(timezone.utc) - start).total_seconds() / 3600.0, 1)


def _row_to_summary(r) -> dict:
    return {
        "id": str(r["id"]),
        "subject": r["subject"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "last_message": r["last_body"],
        "last_is_staff": r["last_is_staff"],
        "author": r["author"] if "author" in r.keys() else None,
        "first_seen_at": r["first_seen_at"] if "first_seen_at" in r.keys() else None,
        "waiting_hours": _waiting_hours(r),
    }


async def list_mine(conn, user_id, limit: int = 50, offset: int = 0) -> dict:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    total = await conn.fetchval("select count(*) from appeals where user_id=$1", user_id)
    rows = await conn.fetch(
        "select a.id, a.subject, a.status, a.created_at, a.updated_at, a.first_seen_at, "
        "(select body from appeal_messages m where m.appeal_id=a.id order by m.created_at desc limit 1) as last_body, "
        "(select is_staff from appeal_messages m where m.appeal_id=a.id order by m.created_at desc limit 1) as last_is_staff "
        "from appeals a where a.user_id=$1 order by a.updated_at desc limit $2 offset $3",
        user_id, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "items": [_row_to_summary(r) for r in rows]}


async def list_org(conn, org_id, status_filter: Optional[str], limit: int = 50, offset: int = 0) -> dict:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    where = "a.organization_id=$1"
    args: list = [org_id]
    if status_filter:
        args.append(status_filter)
        where += f" and a.status=${len(args)}"
    total = await conn.fetchval(f"select count(*) from appeals a where {where}", *args)
    args_paged = args + [limit, offset]
    rows = await conn.fetch(
        f"select a.id, a.subject, a.status, a.created_at, a.updated_at, a.first_seen_at, "
        "coalesce(u.full_name, u.login) as author, "
        "(select body from appeal_messages m where m.appeal_id=a.id order by m.created_at desc limit 1) as last_body, "
        "(select is_staff from appeal_messages m where m.appeal_id=a.id order by m.created_at desc limit 1) as last_is_staff "
        f"from appeals a join users u on u.id=a.user_id where {where} "
        f"order by a.updated_at desc limit ${len(args) + 1} offset ${len(args) + 2}",
        *args_paged)
    return {"total": total, "limit": limit, "offset": offset,
            "response_hours": await response_hours(conn, org_id),
            "items": [_row_to_summary(r) for r in rows]}


async def response_hours(conn, org_id) -> int:
    """Срок ответа, заявленный организацией («Настройки»). Сам по себе он ничего
    не запрещает — он делает ожидание видимым: без него обращение просто лежит
    в очереди, и понять, что оно залежалось, можно только сверив даты вручную."""
    from ..system import settings_service
    return int((await settings_service.get_org_settings(conn, org_id))["appeal_response_hours"])


async def open_count(conn, org_id) -> dict:
    n = await conn.fetchval("select count(*) from appeals where organization_id=$1 and status='open'", org_id)
    return {"open": n}


async def get_appeal(conn, org_id, user: dict, appeal_id: str) -> dict:
    ap = await conn.fetchrow(
        "select a.id, a.subject, a.status, a.created_at, a.updated_at, a.user_id, a.context, "
        "a.first_seen_at, coalesce(s.full_name, s.login) as first_seen_by_name, "
        "a.user_id as author_id, "
        "coalesce(u.full_name, u.login) as author "
        "from appeals a join users u on u.id=a.user_id "
        "left join users s on s.id=a.first_seen_by "
        "where a.id=$1::uuid and a.organization_id=$2", appeal_id, org_id)
    if ap is None:
        raise AppealsError("Обращение не найдено")
    is_author = str(ap["user_id"]) == str(user["id"])
    is_staff = await _is_staff(conn, user["id"])
    if not is_author and not is_staff:
        raise AppealsError("Обращение не найдено")
    seen_at = ap["first_seen_at"]
    seen_by = ap["first_seen_by_name"]
    if is_staff and not is_author and seen_at is None:
        # Первый просмотр со стороны администрации. Автору это важнее, чем
        # кажется: до первого ответа обращение выглядит так же, как в момент
        # отправки, то есть как будто ушло в пустоту.
        await conn.execute(
            "update appeals set first_seen_at=now(), first_seen_by=$2 where id=$1::uuid and first_seen_at is null",
            appeal_id, user["id"])
        row = await conn.fetchrow("select first_seen_at from appeals where id=$1::uuid", appeal_id)
        seen_at, seen_by = row["first_seen_at"], user.get("full_name") or user.get("login")
        await notif_svc.notify(
            conn, org_id, "appeal.seen", "appeal", appeal_id,
            {"author": seen_by, "subject": ap["subject"]}, [ap["user_id"]])
    msgs = await conn.fetch(
        "select m.id, m.is_staff, m.body, m.created_at, coalesce(u.full_name, u.login, '— (удалён)') as author "
        "from appeal_messages m left join users u on u.id=m.sender_user_id "
        "where m.appeal_id=$1::uuid order by m.created_at", appeal_id)
    # context заполнен только у жалоб, отправленных кнопкой с виджета: он даёт
    # в карточке переход к самому отчёту, а не только рассказ о нём.
    ctx = ap["context"]
    if isinstance(ctx, str):
        import json
        ctx = json.loads(ctx)
    return {
        "id": str(ap["id"]), "subject": ap["subject"], "status": ap["status"],
        "created_at": ap["created_at"], "updated_at": ap["updated_at"], "author": ap["author"],
        # id автора нужен администратору, чтобы из запроса доступа сразу
        # открыть карточку доступа именно этого сотрудника.
        "author_id": str(ap["user_id"]),
        "context": ctx,
        "first_seen_at": seen_at, "first_seen_by": seen_by if seen_at else None,
        "messages": [{"id": str(m["id"]), "is_staff": m["is_staff"], "body": m["body"],
                     "created_at": m["created_at"], "author": m["author"]} for m in msgs],
    }


async def add_message(conn, org_id, user: dict, appeal_id: str, body: str) -> dict:
    ap = await conn.fetchrow(
        "select id, user_id, status from appeals where id=$1::uuid and organization_id=$2", appeal_id, org_id)
    if ap is None:
        raise AppealsError("Обращение не найдено")
    is_staff = await _is_staff(conn, user["id"])
    is_author = str(ap["user_id"]) == str(user["id"])
    if not is_author and not is_staff:
        raise AppealsError("Обращение не найдено")
    # Сотрудник, пишущий в СВОЁМ обращении, выступает заявителем, а не
    # администрацией: его сообщение — не ответ. Иначе жалоба, отправленная
    # администратором (а кнопка «сообщить о проблеме» на виджете доступна и
    # ему), сама себя переводила бы в «есть ответ» и уходила из очереди.
    as_staff = is_staff and not is_author
    body = (body or "").strip()
    if not body:
        raise AppealsError("Пустое сообщение")
    if len(body) > MAX_BODY:
        raise AppealsError(f"Слишком длинное сообщение (максимум {MAX_BODY} символов)")
    row = await conn.fetchrow(
        "insert into appeal_messages(appeal_id, sender_user_id, is_staff, body) values($1::uuid,$2,$3,$4) "
        "returning id, created_at", appeal_id, user["id"], as_staff, body)
    new_status = "answered" if as_staff else "open"
    await conn.execute("update appeals set status=$2, updated_at=now() where id=$1::uuid", appeal_id, new_status)
    if as_staff:
        await notif_svc.notify(
            conn, org_id, "appeal.replied", "appeal", appeal_id,
            {"author": user.get("full_name") or user.get("login"), "snippet": body[:140]}, [ap["user_id"]])
    else:
        mgmt = [u for u in await notif_svc.management_user_ids(conn, org_id) if str(u) != str(user["id"])]
        if mgmt:
            await notif_svc.notify(
                conn, org_id, "appeal.message", "appeal", appeal_id,
                {"author": user.get("full_name") or user.get("login"), "snippet": body[:140]}, mgmt)
    await audit_svc.write_event(
        conn, org_id, user["id"], "update", "appeal", appeal_id,
        old_data={"status": ap["status"]}, new_data={"status": new_status, "is_staff": as_staff, "snippet": body[:200]})
    return {"id": str(row["id"]), "created_at": row["created_at"], "status": new_status}


async def close_appeal(conn, org_id, user: dict, appeal_id: str) -> dict:
    ap = await conn.fetchrow(
        "select id, status from appeals where id=$1::uuid and organization_id=$2", appeal_id, org_id)
    if ap is None:
        raise AppealsError("Обращение не найдено")
    await conn.execute("update appeals set status='closed', updated_at=now() where id=$1::uuid", appeal_id)
    await audit_svc.write_event(
        conn, org_id, user["id"], "update", "appeal", appeal_id,
        old_data={"status": ap["status"]}, new_data={"status": "closed"})
    return {"status": "closed"}
