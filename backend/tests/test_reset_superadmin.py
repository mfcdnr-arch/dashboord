"""Аварийное восстановление доступа суперадминистратора.

Зачем это вообще. Права устроены так, что суперадмина может трогать только
суперадмин, а выдавать роль `superadmin` — тоже только он. Поэтому потерянный
пароль единственного суперадминистратора не восстанавливается НИКАК: админ не
может ни сбросить его пароль, ни завести второго суперадмина, а правка
`SUPERADMIN_PASSWORD` в .env.prod ничего не даёт — `_ensure_account` не трогает
пароль уже существующей учётки. Система при этом продолжает работать, но
операции владельца (удаление дашбордов и показателей, гранты аудита,
самоодобрение) становятся недоступны навсегда.

Граница безопасности здесь — доступ к СЕРВЕРУ: у того, кто имеет shell на
машине, и так есть прямой доступ к базе. Поэтому восстановление — хостовой
скрипт, а не кнопка в интерфейсе; в интерфейсе остаётся профилактика
(предупреждение, что суперадминистратор один).
"""
from __future__ import annotations

import uuid

import pytest

from app import db
from app.modules.auth.security import verify_password
from app.tools import reset_superadmin as rs

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _roles(conn, uid) -> set:
    rows = await conn.fetch(
        "select r.code from user_roles ur join roles r on r.id=ur.role_id where ur.user_id=$1", uid)
    return {r["code"] for r in rows}


async def _mk_user(conn, org_id, login: str, roles: list) -> str:
    uid = await conn.fetchval(
        "insert into users(organization_id, login, password_hash, full_name, must_change_password, is_active) "
        "values($1,$2,'x','Тест',false,true) returning id", org_id, login)
    for code in roles:
        rid = await conn.fetchval("select id from roles where organization_id=$1 and code=$2", org_id, code)
        await conn.execute("insert into user_roles(user_id, role_id) values($1,$2)", uid, rid)
    return uid


async def _drop_user(conn, uid) -> None:
    await conn.execute("delete from audit_log where entity_id=$1", uid)
    await conn.execute("delete from user_roles where user_id=$1", uid)
    await conn.execute("delete from users where id=$1", uid)


async def test_sbros_parolya_edinstvennogo_superadmina(ids):
    """Основной случай: пароль потерян, доступ возвращается."""
    async with db.acquire() as conn:
        # Настоящий суперадмин стенда мешает — временно снимаем у него активность,
        # чтобы «единственным» оказался наш тестовый (в конце возвращаем).
        real = await conn.fetch(
            "select u.id from users u join user_roles ur on ur.user_id=u.id "
            "join roles r on r.id=ur.role_id where r.code='superadmin' and u.is_active and u.organization_id=$1",
            ids["org"])
        for r in real:
            await conn.execute("update users set is_active=false where id=$1", r["id"])
        uid = await _mk_user(conn, ids["org"], f"ztest_sa_{uuid.uuid4().hex[:8]}", ["superadmin", "admin"])
        try:
            res = await rs.reset(conn, ids["org"], password="Ln9!vbQ2xkTp")
            assert res["login"], res
            row = await conn.fetchrow(
                "select password_hash, must_change_password, is_active, password_changed_at from users where id=$1", uid)
            assert verify_password("Ln9!vbQ2xkTp", row["password_hash"]), "пароль не сброшен"
            # Смена при первом входе обязательна: временный пароль печатается на
            # экран сервера и не должен оставаться рабочим.
            assert row["must_change_password"] is True
            assert row["password_changed_at"] is not None, "старые токены не отозваны"
            n = await conn.fetchval(
                "select count(*) from audit_log where entity_id=$1 and entity_type='user'", uid)
            assert n >= 1, "аварийное восстановление не попало в журнал"
        finally:
            await _drop_user(conn, uid)
            for r in real:
                await conn.execute("update users set is_active=true where id=$1", r["id"])


async def test_zablokirovannaya_uchetka_razblokiruetsya(ids):
    """🔴 Сброс пароля заблокированной учётке бесполезен — войти всё равно нельзя."""
    async with db.acquire() as conn:
        uid = await _mk_user(conn, ids["org"], f"ztest_sa_{uuid.uuid4().hex[:8]}", ["superadmin"])
        login = await conn.fetchval("select login from users where id=$1", uid)
        await conn.execute("update users set is_active=false where id=$1", uid)
        try:
            await rs.reset(conn, ids["org"], login=login, password="Ln9!vbQ2xkTp")
            assert await conn.fetchval("select is_active from users where id=$1", uid) is True
        finally:
            await _drop_user(conn, uid)


async def test_neskolko_superadminov_trebuyut_yavnogo_vybora(ids):
    """Гадать, чей пароль сбрасывать, нельзя — отказ называет всех поимённо."""
    async with db.acquire() as conn:
        a = await _mk_user(conn, ids["org"], f"ztest_sa_a_{uuid.uuid4().hex[:6]}", ["superadmin"])
        b = await _mk_user(conn, ids["org"], f"ztest_sa_b_{uuid.uuid4().hex[:6]}", ["superadmin"])
        try:
            with pytest.raises(rs.ResetError) as e:
                await rs.reset(conn, ids["org"], password="Ln9!vbQ2xkTp")
            logins = await conn.fetch("select login from users where id = any($1::uuid[])", [a, b])
            for r in logins:
                assert r["login"] in str(e.value), f"в отказе не назван {r['login']}: {e.value}"
        finally:
            await _drop_user(conn, a)
            await _drop_user(conn, b)


async def test_rol_vydaetsya_kogda_superadminov_ne_ostalos(ids):
    """Учётка владельца удалена или заблокирована — роль выдаётся живому человеку."""
    async with db.acquire() as conn:
        uid = await _mk_user(conn, ids["org"], f"ztest_plain_{uuid.uuid4().hex[:8]}", ["user"])
        login = await conn.fetchval("select login from users where id=$1", uid)
        try:
            res = await rs.reset(conn, ids["org"], grant_to=login, password="Ln9!vbQ2xkTp")
            assert "superadmin" in await _roles(conn, uid), "роль не выдана"
            # admin выдаётся вместе: суперадмин — надмножество, иначе человек
            # получил бы права над пользователями, но не доступ к разделам.
            assert "admin" in await _roles(conn, uid), "admin не выдан вместе с superadmin"
            assert res["granted"] is True
        finally:
            await _drop_user(conn, uid)


async def test_neizvestnyy_login_ne_molchit(ids):
    async with db.acquire() as conn:
        with pytest.raises(rs.ResetError) as e:
            await rs.reset(conn, ids["org"], login="ztest_net_takogo", password="Ln9!vbQ2xkTp")
        assert "ztest_net_takogo" in str(e.value)


async def test_slabyy_parol_otklonyaetsya(ids):
    """Аварийный доступ не повод обходить парольную политику."""
    async with db.acquire() as conn:
        with pytest.raises(rs.ResetError):
            await rs.reset(conn, ids["org"], password="123")


async def test_vse_superadminy_zablokirovany_otkaz_nazyvaet_vykhod(ids):
    """🔴 Заблокированную учётку случайно разблокировать нельзя.

    Блокируют намеренно — человек уволился. Молча «восстановив» такую учётку,
    инструмент вернул бы в систему того, кого из неё убрали. Поэтому отказ и
    два названных выхода: явный --login или выдача роли живому человеку.
    """
    async with db.acquire() as conn:
        real = await conn.fetch(
            "select u.id from users u join user_roles ur on ur.user_id=u.id join roles r on r.id=ur.role_id "
            "where r.code='superadmin' and u.is_active and u.organization_id=$1", ids["org"])
        for r in real:
            await conn.execute("update users set is_active=false where id=$1", r["id"])
        uid = await _mk_user(conn, ids["org"], f"ztest_sa_{uuid.uuid4().hex[:8]}", ["superadmin"])
        await conn.execute("update users set is_active=false where id=$1", uid)
        try:
            with pytest.raises(rs.ResetError) as e:
                await rs.reset(conn, ids["org"], password="Ln9!vbQ2xkTp")
            msg = str(e.value)
            assert "заблокированы" in msg, msg
            assert "--login" in msg and "--grant-to" in msg, "выходы не названы"
            assert await conn.fetchval("select is_active from users where id=$1", uid) is False, \
                "заблокированная учётка была разблокирована без явного указания"
        finally:
            await _drop_user(conn, uid)
            for r in real:
                await conn.execute("update users set is_active=true where id=$1", r["id"])


def test_generator_vsegda_daet_parol_prohodyaschiy_politiku():
    """🔴 Регрессия на дефект, найденный живой проверкой.

    Первая версия брала знаки из общего алфавита, и пароль изредка выходил без
    цифр — аварийное восстановление падало на собственной политике. Отказ «через
    раз» у инструмента, который нужен раз в жизни, недопустим, поэтому буква и
    цифра гарантированы по построению. Прогон многократный: единичная проверка
    такой дефект и пропустила бы.
    """
    from app.modules.auth.security import validate_password
    for _ in range(300):
        pw = rs.generate_password()
        validate_password(pw)          # бросит ValueError, если политика не пройдена
        assert len(pw) == 20
        assert not (set(pw) & set("0O1lI")), f"похожие знаки в пароле: {pw}"


async def test_spisok_polzovateley_soobschaet_skolko_superadminov(client, admin_headers):
    """Профилактика важнее восстановления: тупика не будет, если владельцев двое.

    🔴 Считает СЕРВЕР, а не экран: список постраничный, и второй суперадмин
    может оказаться на другой странице — предупреждение «он один» появлялось бы
    ложно и приучило бы его пролистывать.
    """
    r = await client.get("/users?limit=1", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "superadmin_count" in body, "в списке нет счётчика суперадминистраторов"
    assert len(body["items"]) == 1, "проверяем именно постраничный случай"
    async with db.acquire() as conn:
        real = await conn.fetchval(
            "select count(*) from users u join user_roles ur on ur.user_id=u.id "
            "join roles r on r.id=ur.role_id where r.code='superadmin' and u.is_active")
    assert body["superadmin_count"] == real, "счётчик не совпал с действительностью"


async def test_zablokirovannyy_superadmin_v_schetchik_ne_popadaet(ids, client, admin_headers):
    """Заблокированный доступа не даёт — считать его владельцем нельзя."""
    async with db.acquire() as conn:
        uid = await _mk_user(conn, ids["org"], f"ztest_sa_{uuid.uuid4().hex[:8]}", ["superadmin"])
        try:
            before = (await client.get("/users?limit=1", headers=admin_headers)).json()["superadmin_count"]
            await conn.execute("update users set is_active=false where id=$1", uid)
            after = (await client.get("/users?limit=1", headers=admin_headers)).json()["superadmin_count"]
            assert after == before - 1, f"заблокированный всё ещё в счёте: {before} → {after}"
        finally:
            await _drop_user(conn, uid)
