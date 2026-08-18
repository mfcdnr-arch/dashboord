"""Инструкции и объявления — то, что видит обычный пользователь.

Раньше сотруднику были доступны список отчётов и его кабинет; узнать, как
пользоваться системой или что сегодня идут работы на сервере, было негде.
Здесь два простых механизма:

  • **инструкции** — статьи с разделами; текст пишется в системе, готовый файл
    (.docx/.pdf) можно приложить. Отметка «новое» — по таблице прочтений:
    иначе человеку пришлось бы каждый раз просматривать весь список, чтобы
    понять, добавилось ли что-то;
  • **объявления** — сообщения администратора на главной. У каждого срок показа
    и признак важности: без срока главная за месяц зарастает старыми
    сообщениями, и тогда мимо читателя пройдёт и важное.
"""
from __future__ import annotations

from typing import Optional


class PortalError(Exception):
    """Ошибка раздела инструкций/объявлений."""


# --------------------------------------------------------------------------- #
# Инструкции
# --------------------------------------------------------------------------- #

async def list_instructions(conn, org_id, user_id, *, include_drafts: bool = False,
                            q: Optional[str] = None) -> dict:
    """Список инструкций. Пользователю — только опубликованные.

    `q` ищет и по заголовку, и по тексту: человек помнит формулировку из
    середины инструкции чаще, чем её название.
    """
    where = ["i.organization_id = $1"]
    args: list = [org_id]
    if not include_drafts:
        where.append("i.is_published")
    if q:
        args.append(f"%{q.strip()}%")
        where.append(f"(i.title ilike ${len(args)} or coalesce(i.body,'') ilike ${len(args)})")
    rows = await conn.fetch(
        "select i.id, i.section, i.title, i.body, i.file_name, i.file_size_bytes, "
        "       i.position, i.is_published, i.created_at, i.updated_at, "
        "       (r.user_id is not null) as is_read "
        "from instructions i "
        "left join instruction_reads r on r.instruction_id = i.id and r.user_id = $" + str(len(args) + 1) + " "
        "where " + " and ".join(where) + " "
        "order by coalesce(i.section,'') , i.position, i.created_at",
        *args, user_id)
    items = [{
        "id": str(r["id"]), "section": r["section"], "title": r["title"],
        "body": r["body"], "file_name": r["file_name"], "file_size_bytes": r["file_size_bytes"],
        "position": r["position"], "is_published": r["is_published"],
        "created_at": r["created_at"].isoformat(), "updated_at": r["updated_at"].isoformat(),
        "is_read": r["is_read"],
    } for r in rows]
    return {"items": items, "unread": sum(1 for i in items if not i["is_read"] and i["is_published"])}


async def get_instruction(conn, org_id, instruction_id: str, user_id=None,
                          *, allow_draft: bool = False) -> dict:
    row = await conn.fetchrow(
        "select * from instructions where id=$1::uuid and organization_id=$2", instruction_id, org_id)
    if row is None or (not row["is_published"] and not allow_draft):
        raise PortalError("Инструкция не найдена")
    if user_id is not None:
        # Открыл — значит прочитал. Отметку ставим один раз, повторное открытие
        # ничего не меняет: «новое» должно исчезать, а не мигать.
        await conn.execute(
            "insert into instruction_reads(instruction_id, user_id) values($1,$2) "
            "on conflict do nothing", row["id"], user_id)
    return {
        "id": str(row["id"]), "section": row["section"], "title": row["title"],
        "body": row["body"], "file_name": row["file_name"],
        "file_size_bytes": row["file_size_bytes"], "position": row["position"],
        "is_published": row["is_published"],
        "created_at": row["created_at"].isoformat(), "updated_at": row["updated_at"].isoformat(),
    }


async def create_instruction(conn, org_id, user_id, data: dict) -> dict:
    title = (data.get("title") or "").strip()
    if not title:
        raise PortalError("Название не может быть пустым")
    row = await conn.fetchrow(
        "insert into instructions(organization_id, section, title, body, position, is_published, created_by) "
        "values($1,$2,$3,$4,$5,$6,$7) returning id",
        org_id, (data.get("section") or "").strip() or None, title, data.get("body"),
        int(data.get("position") or 0), bool(data.get("is_published", True)), user_id)
    return await get_instruction(conn, org_id, str(row["id"]), allow_draft=True)


async def update_instruction(conn, org_id, instruction_id: str, patch: dict) -> dict:
    sets, args = [], []
    for field in ("section", "title", "body", "position", "is_published"):
        if field in patch:
            args.append(patch[field])
            sets.append(f"{field}=${len(args)}")
    if not sets:
        raise PortalError("Нечего изменять")
    args.extend([instruction_id, org_id])
    row = await conn.fetchrow(
        f"update instructions set {', '.join(sets)}, updated_at=now() "
        f"where id=${len(args) - 1}::uuid and organization_id=${len(args)} returning id", *args)
    if row is None:
        raise PortalError("Инструкция не найдена")
    return await get_instruction(conn, org_id, instruction_id, allow_draft=True)


async def delete_instruction(conn, org_id, instruction_id: str) -> Optional[str]:
    """Удалить инструкцию. Возвращает ключ файла в хранилище, если он был."""
    row = await conn.fetchrow(
        "delete from instructions where id=$1::uuid and organization_id=$2 returning file_path",
        instruction_id, org_id)
    if row is None:
        raise PortalError("Инструкция не найдена")
    return row["file_path"]


async def set_file(conn, org_id, instruction_id: str, path: str, name: str, size: int) -> dict:
    row = await conn.fetchrow(
        "update instructions set file_path=$3, file_name=$4, file_size_bytes=$5, updated_at=now() "
        "where id=$1::uuid and organization_id=$2 returning id", instruction_id, org_id, path, name, size)
    if row is None:
        raise PortalError("Инструкция не найдена")
    return await get_instruction(conn, org_id, instruction_id, allow_draft=True)


async def file_of(conn, org_id, instruction_id: str, *, allow_draft: bool = False) -> dict:
    row = await conn.fetchrow(
        "select file_path, file_name, is_published from instructions "
        "where id=$1::uuid and organization_id=$2", instruction_id, org_id)
    if row is None or (not row["is_published"] and not allow_draft) or not row["file_path"]:
        raise PortalError("Файл не найден")
    return {"path": row["file_path"], "name": row["file_name"]}


# --------------------------------------------------------------------------- #
# Объявления
# --------------------------------------------------------------------------- #

async def list_announcements(conn, org_id, *, only_active: bool = True) -> list:
    """Объявления. Пользователю — только действующие сейчас.

    Срок проверяется в БД, а не на клиенте: иначе объявление продолжало бы
    висеть у того, кто не перезагружал вкладку.
    """
    where = ["organization_id = $1"]
    if only_active:
        where.append("is_active and starts_at <= now() and (ends_at is null or ends_at > now())")
    rows = await conn.fetch(
        "select id, title, body, important, starts_at, ends_at, is_active, created_at "
        "from announcements where " + " and ".join(where) + " "
        "order by important desc, starts_at desc", org_id)
    return [{
        "id": str(r["id"]), "title": r["title"], "body": r["body"], "important": r["important"],
        "starts_at": r["starts_at"].isoformat(),
        "ends_at": r["ends_at"].isoformat() if r["ends_at"] else None,
        "is_active": r["is_active"], "created_at": r["created_at"].isoformat(),
    } for r in rows]


async def create_announcement(conn, org_id, user_id, data: dict) -> dict:
    title = (data.get("title") or "").strip()
    body = (data.get("body") or "").strip()
    if not title or not body:
        raise PortalError("Заполните заголовок и текст объявления")
    row = await conn.fetchrow(
        "insert into announcements(organization_id, title, body, important, ends_at, created_by) "
        # $5::text::timestamptz, а не $5::timestamptz: asyncpg на прямом касте
        # требует datetime, а из формы приходит строка (грабли проекта).
        "values($1,$2,$3,$4,$5::text::timestamptz,$6) returning id",
        org_id, title, body, bool(data.get("important")), data.get("ends_at"), user_id)
    got = await list_announcements(conn, org_id, only_active=False)
    return next(a for a in got if a["id"] == str(row["id"]))


async def update_announcement(conn, org_id, announcement_id: str, patch: dict) -> dict:
    sets, args = [], []
    for field in ("title", "body", "important", "is_active"):
        if field in patch:
            args.append(patch[field])
            sets.append(f"{field}=${len(args)}")
    if "ends_at" in patch:
        args.append(patch["ends_at"])
        sets.append(f"ends_at=${len(args)}::text::timestamptz")
    if not sets:
        raise PortalError("Нечего изменять")
    args.extend([announcement_id, org_id])
    row = await conn.fetchrow(
        f"update announcements set {', '.join(sets)}, updated_at=now() "
        f"where id=${len(args) - 1}::uuid and organization_id=${len(args)} returning id", *args)
    if row is None:
        raise PortalError("Объявление не найдено")
    got = await list_announcements(conn, org_id, only_active=False)
    return next(a for a in got if a["id"] == announcement_id)


async def delete_announcement(conn, org_id, announcement_id: str) -> None:
    row = await conn.fetchrow(
        "delete from announcements where id=$1::uuid and organization_id=$2 returning id",
        announcement_id, org_id)
    if row is None:
        raise PortalError("Объявление не найдено")
