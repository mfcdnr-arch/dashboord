"""Смена пароля требует текущий пароль (находка аудита).

Без него любой, кто оказался за незаблокированным компьютером, менял пароль
владельца: смена отзывает ВСЕ прежние токены (миграция 033), то есть
настоящего хозяина выбрасывало из системы, а чужой доступ становился
постоянным. Знание текущего пароля — единственное, что отличает владельца от
того, кто просто сел за его стол.

Второе правило здесь не про удобство: новый пароль не может совпадать с
текущим. Иначе обязательная смена временного пароля обходится вводом того же
самого временного — `must_change_password` снимается, и выданный админом
пароль становится постоянным.
"""
import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio(loop_scope="session")

from app import db
from app.modules.auth.security import hash_password

LOGIN = "ztest_pwd_current"
OLD = "OldPass2026!"
NEW = "NewPass2026!"


@pytest_asyncio.fixture
async def person(ids):
    """Сотрудник с известным паролем; must_change_password задаётся тестом."""
    async with db.acquire() as conn:
        await conn.execute("delete from user_roles where user_id in (select id from users where login=$1)", LOGIN)
        await conn.execute("delete from login_events where login=$1", LOGIN)
        await conn.execute("delete from users where login=$1", LOGIN)
        uid = await conn.fetchval(
            "insert into users(organization_id, login, full_name, password_hash, is_active, must_change_password) "
            "values($1,$2,'Тест смены пароля',$3,true,false) returning id",
            ids["org"], LOGIN, hash_password(OLD))
        role = await conn.fetchval("select id from roles where code='user' and organization_id=$1", ids["org"])
        if role:
            await conn.execute("insert into user_roles(user_id, role_id) values($1,$2)", uid, role)
    yield {"id": str(uid), "login": LOGIN, "password": OLD}
    async with db.acquire() as conn:
        await conn.execute("delete from user_roles where user_id=$1", uid)
        await conn.execute("delete from login_events where user_id=$1", uid)
        await conn.execute("delete from users where id=$1", uid)


async def _token(client, login, password):
    r = await client.post("/auth/login", data={"username": login, "password": password})
    return r.json().get("access_token") if r.status_code == 200 else None


async def test_change_without_current_password_is_refused(client, person):
    """Тело без текущего пароля не принимается вовсе."""
    token = await _token(client, LOGIN, OLD)
    r = await client.post("/auth/change-password", headers={"Authorization": f"Bearer {token}"},
                          json={"new_password": NEW})
    assert r.status_code in (400, 422), r.text
    # и пароль остался прежним — вход по старому по-прежнему работает
    assert await _token(client, LOGIN, OLD) is not None
    assert await _token(client, LOGIN, NEW) is None


async def test_wrong_current_password_does_not_change_anything(client, person):
    """Чужой за компьютером не сменит пароль, не зная текущего."""
    token = await _token(client, LOGIN, OLD)
    r = await client.post("/auth/change-password", headers={"Authorization": f"Bearer {token}"},
                          json={"current_password": "ЧужойПароль2026!", "new_password": NEW})
    assert r.status_code == 400, r.text
    assert await _token(client, LOGIN, OLD) is not None
    assert await _token(client, LOGIN, NEW) is None


async def test_correct_current_password_changes_it(client, person):
    """Владелец меняет пароль: новый работает, старый перестаёт."""
    token = await _token(client, LOGIN, OLD)
    r = await client.post("/auth/change-password", headers={"Authorization": f"Bearer {token}"},
                          json={"current_password": OLD, "new_password": NEW})
    assert r.status_code == 200, r.text
    assert r.json().get("access_token"), "смена отзывает токены — новый должен прийти сразу"
    assert await _token(client, LOGIN, NEW) is not None
    assert await _token(client, LOGIN, OLD) is None


async def test_new_password_cannot_repeat_the_current_one(client, person):
    """Тот же пароль не считается сменой — иначе временный станет постоянным."""
    async with db.acquire() as conn:
        await conn.execute("update users set must_change_password=true where id=$1::uuid", person["id"])
    token = await _token(client, LOGIN, OLD)
    r = await client.post("/auth/change-password", headers={"Authorization": f"Bearer {token}"},
                          json={"current_password": OLD, "new_password": OLD})
    assert r.status_code == 400, r.text
    async with db.acquire() as conn:
        must = await conn.fetchval("select must_change_password from users where id=$1::uuid", person["id"])
    assert must is True, "требование сменить временный пароль не должно сниматься"


async def test_mandatory_change_works_with_the_temporary_password(client, person):
    """Обязательная смена проходит: временный пароль человек только что вводил."""
    async with db.acquire() as conn:
        await conn.execute("update users set must_change_password=true where id=$1::uuid", person["id"])
    token = await _token(client, LOGIN, OLD)
    r = await client.post("/auth/change-password", headers={"Authorization": f"Bearer {token}"},
                          json={"current_password": OLD, "new_password": NEW})
    assert r.status_code == 200, r.text
    async with db.acquire() as conn:
        must = await conn.fetchval("select must_change_password from users where id=$1::uuid", person["id"])
    assert must is False
    assert await _token(client, LOGIN, NEW) is not None
