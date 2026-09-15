"""Аварийное восстановление доступа суперадминистратора.

Права устроены так, что суперадмина может трогать только суперадмин, а
выдавать роль `superadmin` — тоже только он. Это верно по существу, но даёт
тупик: потерянный пароль ЕДИНСТВЕННОГО суперадминистратора не восстанавливается
никак. Админ не может ни сбросить его пароль, ни завести второго суперадмина;
правка `SUPERADMIN_PASSWORD` в .env.prod тоже не помогает — первичная
инициализация не трогает пароль уже существующей учётки. Система продолжает
работать, но операции владельца (удаление дашбордов и показателей, гранты
аудита, самоодобрение) становятся недоступны навсегда.

Выход — здесь, и он намеренно НЕ в интерфейсе: граница безопасности этой
операции — доступ к серверу. Запускается обёрткой `reset-superadmin.sh`.

Что делает:
  • сбрасывает пароль суперадминистратора (и разблокирует учётку — иначе сброс
    бесполезен, войти всё равно нельзя);
  • при нескольких суперадминах требует явного выбора: гадать, чей пароль
    менять, нельзя;
  • `--grant-to LOGIN` выдаёт роль живому человеку, когда суперадминов не
    осталось вовсе (учётку удалили или заблокировали);
  • пишет в журнал действий — аварийный доступ обязан оставлять след.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import string
import sys

from ..modules.auth.security import hash_password, validate_password

SUPERADMIN = "superadmin"
# Суперадмин — надмножество admin: без второй роли человек получил бы права над
# пользователями, но не доступ к разделам (см. bootstrap.ensure_seed).
GRANT_ROLES = (SUPERADMIN, "admin")


class ResetError(Exception):
    """Ошибка, которую должен прочитать человек у консоли, а не стектрейс."""


# Знаки, похожие друг на друга (0/O, 1/l/I), исключены: пароль читают с экрана
# сервера и набирают руками, а опечатка здесь стоит второго захода.
_LOWER = string.ascii_lowercase.replace("l", "")
_UPPER = string.ascii_uppercase.replace("O", "").replace("I", "")
_DIGITS = "23456789"
_SPECIAL = "!@#%^*-_=+"


def generate_password(length: int = 20) -> str:
    """Временный пароль для одноразового входа.

    🔴 Буква и цифра гарантированы по построению, а не «скорее всего». Первая
    версия брала все знаки из общего алфавита, и пароль изредка выходил без
    цифр — тогда аварийное восстановление падало на собственной парольной
    политике. Случайный отказ у инструмента, который нужен раз в жизни и именно
    в критический момент, — худшее, что здесь можно допустить (поймано живой
    проверкой, а не тестом).
    """
    required = [secrets.choice(_LOWER), secrets.choice(_UPPER),
                secrets.choice(_DIGITS), secrets.choice(_SPECIAL)]
    pool = _LOWER + _UPPER + _DIGITS + _SPECIAL
    rest = [secrets.choice(pool) for _ in range(max(0, length - len(required)))]
    chars = required + rest
    # Перемешиваем, иначе первые четыре знака всегда шли бы в одном порядке.
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


async def _superadmins(conn, org_id) -> list:
    return await conn.fetch(
        "select u.id, u.login, u.full_name, u.is_active from users u "
        "join user_roles ur on ur.user_id = u.id join roles r on r.id = ur.role_id "
        "where u.organization_id = $1 and r.code = $2 order by u.login", org_id, SUPERADMIN)


async def reset(conn, org_id, login: str | None = None, grant_to: str | None = None,
                password: str | None = None) -> dict:
    """Вернуть доступ владельцу. Возвращает сведения для печати у консоли."""
    password = password or generate_password()
    try:
        validate_password(password)
    except ValueError as e:
        # Аварийный доступ — не повод обходить парольную политику: временный
        # пароль так же уводит учётку, как и постоянный.
        raise ResetError(f"Пароль не проходит политику: {e}")

    granted = False
    if grant_to:
        target = await conn.fetchrow(
            "select id, login, full_name, is_active from users where organization_id=$1 and login=$2",
            org_id, grant_to)
        if not target:
            raise ResetError(f"Пользователь «{grant_to}» не найден — проверьте логин")
        for code in GRANT_ROLES:
            rid = await conn.fetchval("select id from roles where organization_id=$1 and code=$2", org_id, code)
            if rid is None:
                raise ResetError(f"В организации нет системной роли «{code}» — база повреждена")
            await conn.execute(
                "insert into user_roles(user_id, role_id) values($1,$2) on conflict do nothing", target["id"], rid)
        granted = True
    else:
        rows = await _superadmins(conn, org_id)
        if not rows:
            raise ResetError(
                "В системе нет ни одного суперадминистратора. Выдайте роль живому человеку: "
                "./reset-superadmin.sh --grant-to ЛОГИН")
        if login:
            target = next((r for r in rows if r["login"] == login), None)
            if target is None:
                names = ", ".join(r["login"] for r in rows)
                raise ResetError(f"Суперадминистратор «{login}» не найден. Есть: {names}")
        else:
            # 🔴 Выбираем среди АКТИВНЫХ. Заблокированную учётку блокируют
            # намеренно (человек уволился), и случайно разблокировать её при
            # восстановлении нельзя — только по явному --login.
            active = [r for r in rows if r["is_active"]]
            if not active:
                names = ", ".join(r["login"] for r in rows)
                raise ResetError(
                    f"Все суперадминистраторы заблокированы: {names}. Если восстанавливать нужно "
                    f"одного из них — укажите явно: ./reset-superadmin.sh --login ЛОГИН; "
                    f"если нет — выдайте роль другому: --grant-to ЛОГИН")
            rows = active
        if not login and len(rows) > 1:
            # Гадать, чей пароль менять, нельзя: сброс выкидывает человека из
            # всех сессий, и промах ударил бы по работающему сотруднику.
            names = ", ".join(f"{r['login']} ({r['full_name']})" for r in rows)
            raise ResetError(
                f"Суперадминистраторов несколько — укажите, кого восстанавливать: {names}\n"
                "  ./reset-superadmin.sh --login ЛОГИН")
        elif not login:
            target = rows[0]

    was_blocked = not target["is_active"]
    await conn.execute(
        "update users set password_hash=$2, must_change_password=true, is_active=true, "
        "password_changed_at=date_trunc('second', now()) where id=$1",
        target["id"], hash_password(password))

    # Актор не указан намеренно: операцию выполнил не пользователь системы, а
    # тот, у кого есть доступ к серверу. Запись всё равно обязательна — иначе
    # аварийный вход в систему не оставил бы следа вовсе.
    await conn.execute(
        "insert into audit_log(organization_id, actor_user_id, action, entity_type, entity_id, new_data) "
        "values($1, null, 'update', 'user', $2, $3::jsonb)",
        org_id, target["id"], json.dumps({
            "event": "emergency_superadmin_reset",
            "login": target["login"],
            "granted_role": granted,
            "unblocked": was_blocked,
            "source": "reset-superadmin.sh (доступ к серверу)",
        }, ensure_ascii=False))

    return {
        "login": target["login"],
        "full_name": target["full_name"],
        "password": password,
        "granted": granted,
        "unblocked": was_blocked,
    }


async def _main() -> int:
    ap = argparse.ArgumentParser(description="Аварийное восстановление доступа суперадминистратора")
    ap.add_argument("--login", help="логин суперадминистратора (нужен, если их несколько)")
    ap.add_argument("--grant-to", dest="grant_to",
                    help="выдать роль суперадминистратора этому пользователю (если их не осталось)")
    ap.add_argument("--password", help="задать пароль вручную (по умолчанию генерируется)")
    args = ap.parse_args()

    from .. import db
    await db.connect()
    try:
        async with db.get_pool().acquire() as conn:
            org_id = await conn.fetchval("select id from organizations order by created_at limit 1")
            if org_id is None:
                raise ResetError("В базе нет ни одной организации — система не инициализирована")
            async with conn.transaction():
                res = await reset(conn, org_id, login=args.login, grant_to=args.grant_to,
                                  password=args.password)
        print(json.dumps(res, ensure_ascii=False))
        return 0
    except ResetError as e:
        print(f"ОШИБКА: {e}", file=sys.stderr)
        return 2
    finally:
        await db.disconnect()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
