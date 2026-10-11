"""Своя база для прогона тестов (11.10.2026).

До этого тесты работали на базе дев-стенда. Цена была двойная: живую проверку
приходилось откладывать, пока идёт прогон (уборка `_purge_leftovers` сносила
временные данные проверки посреди работы), а сами тесты зависели от того, что
лежит на стенде.

Теперь сервис `tests` в dev-compose указывает на `dashbord_test` и ставит
`TEST_DB_RECREATE=1`: перед сессией база пересоздаётся с нуля и в неё
накатываются ВСЕ миграции из `db/migrations` — тем же порядком и по одной
транзакции на файл, как это делает `db/run-migrations.sh` в бою. Так каждый
прогон заодно проверяет, что миграции встают на пустую базу.

🔴 Удаляется только база, чьё имя оканчивается на `_test`: опечатка в
окружении не должна стоить базы стенда. CI пересоздавать нечего — у него свой
одноразовый Postgres, и без `TEST_DB_RECREATE` здесь ничего не происходит.
"""
from __future__ import annotations

import os
from pathlib import Path

import asyncpg

_MIG = [Path("/migrations"), Path(__file__).resolve().parents[2] / "db" / "migrations"]


def _dsn(database: str) -> dict:
    return {"host": os.environ.get("POSTGRES_HOST", "localhost"),
            "port": int(os.environ.get("POSTGRES_PORT", "5432")),
            "user": os.environ.get("POSTGRES_USER", "dashbord"),
            "password": os.environ.get("POSTGRES_PASSWORD", "dashbord"),
            "database": database}


async def recreate_if_asked() -> None:
    if os.environ.get("TEST_DB_RECREATE") != "1":
        return
    name = os.environ.get("POSTGRES_DB", "")
    if not name.endswith("_test"):
        raise RuntimeError(f"TEST_DB_RECREATE=1, но база «{name}» не тестовая (имя должно оканчиваться "
                           "на _test) — пересоздавать её нельзя")
    migdir = next((p for p in _MIG if p.is_dir()), None)
    if migdir is None:
        raise RuntimeError("Каталог миграций не найден — смонтируйте db/migrations в /migrations")

    admin = await asyncpg.connect(**_dsn("postgres"))
    try:
        await admin.execute(
            "select pg_terminate_backend(pid) from pg_stat_activity where datname = $1 "
            "and pid <> pg_backend_pid()", name)
        await admin.execute(f'drop database if exists "{name}"')
        await admin.execute(f'create database "{name}"')
    finally:
        await admin.close()

    conn = await asyncpg.connect(**_dsn(name))
    try:
        await conn.execute("create table schema_migrations(filename text primary key, "
                           "applied_at timestamptz not null default now())")
        for f in sorted(migdir.glob("*.sql")):
            async with conn.transaction():
                await conn.execute(f.read_text(encoding="utf-8"))
                await conn.execute("insert into schema_migrations(filename) values($1)", f.name)
    finally:
        await conn.close()
