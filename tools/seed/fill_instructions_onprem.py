# -*- coding: utf-8 -*-
"""Наполнение «Инструкций» на БОЕВОМ сервере.

Почему не исходный `tools/seed/fill_instructions.py`: он ходит через HTTP на
`localhost:8080` и логинится парой `admin/admin` — это дев-стенд. На боевом
пароль администратора принадлежит заказчику; подбирать его нельзя (а неудачные
попытки ещё и запирают учётку защитой от перебора).

Поэтому берём ТЕ ЖЕ тексты (импортом из того же файла — второй копии материалов
не заводим) и пишем их ТЕМИ ЖЕ функциями приложения, что вызывает роутер:
`portal.service.create_instruction` / `update_instruction` / `set_file` и
`documents.storage.put_object`. Своей логики здесь нет — иначе сид однажды
разошёлся бы с тем, что делает кнопка в интерфейсе.

Идемпотентно по заголовку: материал с тем же названием обновляется.
"""
import asyncio
import importlib.util
import os
import sys

sys.path.insert(0, "/app")

from app import db                                    # noqa: E402
from app.modules.documents import storage             # noqa: E402
from app.modules.portal import router as portal_router  # noqa: E402
from app.modules.portal import service as portal      # noqa: E402

DOCS = "/tmp/seed/docs"
SEED = "/tmp/seed/fill_instructions.py"


def _load_materials():
    spec = importlib.util.spec_from_file_location("seed_src", SEED)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)          # main() под __name__-guard, не выполнится
    return mod.MATERIALS, mod.FILES


async def main():
    materials, files = _load_materials()
    await db.connect()
    async with db.get_pool().acquire() as conn:
        org_id = await conn.fetchval("select id from organizations order by created_at limit 1")
        # Автор — учётка администратора организации: created_by NOT NULL, и
        # приписать материалы можно только живому пользователю.
        actor = await conn.fetchrow(
            "select u.id, u.login from users u join user_roles ur on ur.user_id=u.id "
            "join roles r on r.id=ur.role_id "
            "where u.organization_id=$1 and u.is_active and r.code in ('admin','superadmin') "
            "order by (u.login='admin') desc, u.created_at limit 1", org_id)
        if actor is None:
            print("НЕ НАЙДЕН администратор организации — ничего не делаю")
            return 1
        print(f"организация {org_id}, автор материалов: {actor['login']}")

    async with db.acquire(str(actor["id"])) as conn:
        existing = {i["title"]: i for i in
                    (await portal.list_instructions(
                        conn, org_id, actor["id"], include_drafts=True))["items"]}
        created = updated = 0

        for section, title, pos, body, _ in materials:
            payload = {"title": title, "section": section, "body": body,
                       "position": pos, "is_published": True}
            if title in existing:
                await portal.update_instruction(conn, org_id, existing[title]["id"], payload)
                updated += 1
            else:
                await portal.create_instruction(conn, org_id, actor["id"], payload)
                created += 1

        for section, title, pos, body, fname in files:
            payload = {"title": title, "section": section, "body": body,
                       "position": pos, "is_published": True}
            if title in existing:
                item = await portal.update_instruction(conn, org_id, existing[title]["id"], payload)
                updated += 1
            else:
                item = await portal.create_instruction(conn, org_id, actor["id"], payload)
                created += 1
            iid = str(item["id"])
            path = os.path.join(DOCS, fname)
            with open(path, "rb") as fh:
                data = fh.read()
            ext = "." + fname.rsplit(".", 1)[-1].lower()
            if ext not in portal_router.ALLOWED:
                print(f"  ПРОПУЩЕН файл {fname}: формат не разрешён")
                continue
            if len(data) > portal_router.MAX_FILE_MB * 1024 * 1024:
                print(f"  ПРОПУЩЕН файл {fname}: больше {portal_router.MAX_FILE_MB} МБ")
                continue
            # Ключ и тип — те же, что ставит роутер загрузки.
            key = storage.put_object(f"instructions/{iid}/{fname}", data,
                                     portal_router.ALLOWED[ext])
            await portal.set_file(conn, org_id, iid, key, fname, len(data))
            print(f"  + файл {fname} ({len(data)/1048576:.1f} МБ)")

        total = (await portal.list_instructions(
            conn, org_id, actor["id"], include_drafts=True))["items"]
        print(f"\nсоздано: {created}, обновлено: {updated}")
        print(f"Всего материалов: {len(total)}")
        for i in total:
            mark = "  📎 " + i["file_name"] if i.get("file_name") else ""
            print(f"  [{i.get('section') or '—'}] {i['position']:>3} {i['title']}{mark}")
    await db.disconnect()
    return 0


sys.exit(asyncio.run(main()))
