#!/bin/sh
# Раннер миграций с трекингом: применяет каждый файл db/migrations/*.sql
# РОВНО ОДИН РАЗ (часть миграций не идемпотентна — create type/table без
# IF NOT EXISTS). На чистой БД применит все; на обновлении — только новые.
# Запускается как one-shot сервис `migrate` в docker-compose.prod.yml.
set -eu

PGHOST="${POSTGRES_HOST:-postgres}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER="${POSTGRES_USER:-dashbord}"
PGDATABASE="${POSTGRES_DB:-dashbord}"
export PGPASSWORD="${POSTGRES_PASSWORD:-dashbord}"
# Каталог с миграциями: в контейнере смонтирован в /migrations; в CI/локально
# можно переопределить (MIGRATIONS_DIR=db/migrations).
MIGDIR="${MIGRATIONS_DIR:-/migrations}"
PSQL="psql -v ON_ERROR_STOP=1 -h $PGHOST -p $PGPORT -U $PGUSER -d $PGDATABASE"

echo "[migrate] ждём готовности PostgreSQL $PGHOST:$PGPORT ..."
i=0
until $PSQL -c 'select 1' >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then echo "[migrate] БД не поднялась за 120с — выходим"; exit 1; fi
  sleep 2
done

$PSQL -c "create table if not exists schema_migrations(
  filename text primary key,
  applied_at timestamptz not null default now())" >/dev/null

applied=0
for f in "$MIGDIR"/*.sql; do
  name="$(basename "$f")"
  exists="$($PSQL -tAc "select 1 from schema_migrations where filename='$name'")"
  if [ -n "$exists" ]; then
    echo "[migrate] = $name (уже применена)"
    continue
  fi
  echo "[migrate] → применяю $name"
  $PSQL --single-transaction -f "$f"
  $PSQL -c "insert into schema_migrations(filename) values('$name')" >/dev/null
  applied=$((applied + 1))
done

echo "[migrate] Готово. Новых миграций применено: $applied"
