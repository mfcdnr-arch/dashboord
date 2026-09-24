#!/usr/bin/env bash
# Проверка бэкапа НАСТОЯЩИМ восстановлением — в отдельную временную базу.
# Рабочую систему не трогает: боевая база только читается (подсчёт строк),
# восстановление идёт в свой контейнер без сети, который удаляется в конце
# вместе со своим томом данных.
#
#   ./restore-check.sh                     # последний годный набор
#   ./restore-check.sh backups/<TS>        # конкретный набор
#
# Зачем. backup.sh проверяет, что дамп ЧИТАЕТСЯ (pg_restore --list), — это
# оглавление, а не база: дамп с целым оглавлением может не восстановиться
# (роль, расширение, порядок зависимостей), и узнают об этом в день аварии.
# Здесь дамп восстанавливается той же командой, что в restore.sh.
#
# С ЧЕМ сверяем — два разных вопроса, и путать их нельзя:
#   • «набор цел» — с САМИМ набором: каждая таблица из оглавления дампа
#     восстановилась, миграций столько же, сколько было при бэкапе (meta.txt).
#     Несовпадение здесь — негодный бэкап (код 1).
#   • «насколько набор отстал» — с РАБОЧЕЙ базой: число строк по таблицам,
#     таблицы, появившиеся после бэкапа. Это сведения, а не приговор (код 3):
#     deploy.sh делает бэкап ДО миграций, и сверка «таблица есть в рабочей, но
#     нет в наборе» объявляла бы исправный бэкап негодным ровно после каждого
#     обновления (находка ревью 24.09.2026).
# Архив MinIO распаковывается во временный том и сверяется с рабочим по числу
# и объёму объектов (служебный .minio.sys не считается).
#
# Код выхода: 0 — восстановилось и совпало с рабочей базой; 3 — восстановилось,
# набор цел, но рабочая база ушла вперёд (перечислено что); 1 — не восстановилось
# или набор неполон. Итог: ops-triggers/restore-check.result (JSON) и
# ops-triggers/restore-check.txt (отчёт). В каталог набора НЕ пишем: время его
# изменения используют ротация и экран «Последний успешный бэкап».
set -euo pipefail
cd "$(dirname "$0")"

env_get() { { grep -E "^$1=" .env.prod 2>/dev/null | cut -d= -f2- | tail -1; } || true; }
PGUSER="$(env_get POSTGRES_USER)"; PGUSER="${PGUSER:-dashbord}"
PGDB="$(env_get POSTGRES_DB)"; PGDB="${PGDB:-dashbord}"
# Каталог наборов — так же, как у backup-schedule.sh: окружение, затем .env.prod.
# Иначе при вынесенных на отдельный диск бэкапах (так советует документация)
# проверялся бы старый набор из ./backups, а ночные — никогда.
BACKUP_DIR="${BACKUP_DIR:-$(env_get BACKUP_DIR)}"; BACKUP_DIR="${BACKUP_DIR:-backups}"
LIVE_PG="${PG_CONTAINER:-dashbord_prod_postgres}"
MINIO_VOLUME="${MINIO_VOLUME:-dashbord-prod_miniodata}"
TRIGGER_DIR="${OPS_TRIGGER_DIR:-ops-triggers}"
RESULT_FILE="$TRIGGER_DIR/restore-check.result"
REPORT="$TRIGGER_DIR/restore-check.txt"

# Имена временных объектов фиксированы и начинаются с dashbord_restorecheck —
# по ним скрипт убирает за собой, в том числе остатки прерванного прошлого запуска.
# Данные временной базы — в ИМЕНОВАННОМ томе: образ postgres объявляет том под
# PGDATA, и без явного тома Docker создавал бы анонимный, который `docker rm -f`
# не удаляет, — каждый прогон оставлял бы на диске полную копию боевой базы
# (вместе с хешами паролей), о которой никто не знает.
TMP_PG="dashbord_restorecheck_pg"
TMP_PGDATA="dashbord_restorecheck_pgdata"
TMP_VOL="dashbord_restorecheck_minio"

log() { printf '\033[1;34m[restore-check]\033[0m %s\n' "$1"; }
bad() { printf '\033[1;31m[restore-check]\033[0m %s\n' "$1" >&2; }

# Непредвиденный сбой обязан назвать себя — с самого начала скрипта. Без этого
# set -e обрывал бы скрипт молча (так и случилось на первом прогоне: df по
# невидимому с хоста пути).
on_err() {
  MESSAGE="Сбой на строке $1: $(printf '%s' "$2" | tr '"' "'" | cut -c1-160)"
  bad "$MESSAGE"
}
trap 'on_err "$LINENO" "$BASH_COMMAND"' ERR

# Склонение: plural 5 таблица таблицы таблиц → «5 таблиц».
plural() {
  local n="$1" m10=$(( $1 % 10 )) m100=$(( $1 % 100 ))
  if [ "$m10" = 1 ] && [ "$m100" != 11 ]; then echo "$n $2"
  elif [ "$m10" -ge 2 ] && [ "$m10" -le 4 ] && { [ "$m100" -lt 12 ] || [ "$m100" -gt 14 ]; }; then echo "$n $3"
  else echo "$n $4"; fi
}
# Объекты MinIO: число файлов и их объём, БЕЗ служебного .minio.sys — там
# корзина и временные файлы самого MinIO, они меняются каждую минуту и к данным
# отношения не имеют (на первом прогоне дали ложное «расходится» на 12 файлов).
MINIO_STATS='find /data -path /data/.minio.sys -prune -o -type f -exec stat -c %s {} + | awk "{n++; s+=\$1} END {print n+0, s+0}"'

SET="${1:-}"
if [ -z "$SET" ]; then
  # Последний ГОДНЫЙ набор — по ИМЕНИ (оно и есть время бэкапа), а не по времени
  # изменения каталога: его сдвигает любая запись внутрь. Провалившийся
  # (FAILED.txt) и недописанный (нет db.dump) проверять бессмысленно, а выдать
  # его за «последний бэкап» хуже, чем молчать. Перебор — циклом по подстановке
  # процесса, а не каналом с `head -1`: при pipefail канал обрывал скрипт то
  # на пустом каталоге, то по SIGPIPE (код 141), когда head закрывался раньше
  # цикла, — оба случая поймали тесты.
  while IFS= read -r d; do
    if [ -z "$SET" ] && [ ! -f "$d/FAILED.txt" ] && [ -f "$d/db.dump" ]; then SET="${d%/}"; fi
  done < <(ls -1d "$BACKUP_DIR"/*/ 2>/dev/null | sort -r)
fi
[ -n "$SET" ] && [ -f "$SET/db.dump" ] || {
  bad "Нет набора для проверки (ищу $BACKUP_DIR/<TS>/db.dump). Сначала ./backup.sh"
  exit 1
}
SET="${SET%/}"
SET_NAME="$(basename "$SET")"
# Абсолютный путь — для монтирования в контейнер (docker принимает только его).
SET_ABS="$(cd "$SET" && pwd)"

# Один запуск за раз: второй экземпляр убрал бы временный контейнер из-под первого.
LOCK="$TRIGGER_DIR/restore-check.lock"
mkdir -p "$TRIGGER_DIR"
if ! mkdir "$LOCK" 2>/dev/null; then
  bad "Проверка уже идёт (есть $LOCK). Если это остаток прерванного запуска — удалите каталог и повторите."
  exit 1
fi

STATUS="fail"; MESSAGE="Проверка прервана"
write_result() {
  local ok=false; [ "$STATUS" != fail ] && ok=true
  printf '{"ts":"%s","ok":%s,"status":"%s","message":"%s","set":"%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$ok" "$STATUS" "$MESSAGE" "$SET_NAME" > "$RESULT_FILE" 2>/dev/null || true
}
remove_temp() {
  docker rm -f -v "$TMP_PG" >/dev/null 2>&1 || true
  docker volume rm -f "$TMP_PGDATA" >/dev/null 2>&1 || true
  docker volume rm -f "$TMP_VOL" >/dev/null 2>&1 || true
}
cleanup() {
  remove_temp
  write_result
  rmdir "$LOCK" 2>/dev/null || true
}
# Уборка при ЛЮБОМ выходе, включая падение по set -e и обрыв ssh: временная
# база весит столько же, сколько рабочая, и забытая копия тихо съела бы диск.
trap cleanup EXIT

docker inspect "$LIVE_PG" >/dev/null 2>&1 || { MESSAGE="Контейнер $LIVE_PG не запущен — сверять не с чем"; bad "$MESSAGE"; exit 1; }
IMAGE="$(docker inspect -f '{{.Config.Image}}' "$LIVE_PG")"

# Места должно хватить на вторую копию базы: иначе проверка бэкапа сама
# устроила бы аварию, заполнив диск под рабочей системой.
LIVE_MB="$(docker exec "$LIVE_PG" psql -U "$PGUSER" -d "$PGDB" -tAc \
  "select pg_database_size(current_database())/1024/1024" | tr -d '[:space:]')"
# Каталог данных Docker может быть не виден с хоста (Docker Desktop держит его
# внутри своей машины) — тогда меряем каталог проекта: без замера не остаёмся,
# и непрочитанный путь не обрывает проверку.
ROOT="$(docker info -f '{{.DockerRootDir}}' 2>/dev/null || true)"
FREE_MB="$( { df -Pm "${ROOT:-.}" 2>/dev/null || df -Pm . 2>/dev/null; } | awk 'NR==2{print $4}' || true)"
if [ -n "$FREE_MB" ] && [ -n "$LIVE_MB" ] && [ "$FREE_MB" -lt $(( LIVE_MB * 2 + 1024 )) ]; then
  MESSAGE="Мало места: свободно ${FREE_MB} МБ, база ${LIVE_MB} МБ — нужно не меньше $(( LIVE_MB * 2 + 1024 )) МБ"
  bad "$MESSAGE"; exit 1
fi

remove_temp   # остатки прерванного прошлого запуска

log "Набор: $SET (база ${LIVE_MB:-?} МБ, свободно ${FREE_MB:-?} МБ)"
log "Временная база из образа $IMAGE (без сети, 1 ядро, 1,5 ГБ памяти)…"
# Лимиты — чтобы проверка не отнимала ресурсы у рабочей системы, пока идёт.
# Пароль случайный и нигде не нужен: сеть отключена, входим через docker exec.
docker run -d --name "$TMP_PG" --network none --cpus 1 --memory 1536m \
  -v "$TMP_PGDATA":/var/lib/postgresql/data \
  -e POSTGRES_USER="$PGUSER" -e POSTGRES_DB="$PGDB" \
  -e POSTGRES_PASSWORD="rc$(date +%s)$$" "$IMAGE" >/dev/null

ready=""
POLL="${RC_POLL_SEC:-2}"
for _ in $(seq 1 60); do
  # pg_isready отвечает «да» ещё на временном сервере инициализации — ждём
  # настоящий: запрос к базе проходит только после его перезапуска.
  if docker exec "$TMP_PG" psql -U "$PGUSER" -d "$PGDB" -tAc "select 1" >/dev/null 2>&1; then
    sleep "$POLL"
    docker exec "$TMP_PG" psql -U "$PGUSER" -d "$PGDB" -tAc "select 1" >/dev/null 2>&1 && { ready=1; break; }
  fi
  sleep "$POLL"
done
[ -n "$ready" ] || { MESSAGE="Временная база не поднялась за 2 минуты"; bad "$MESSAGE"; exit 1; }

# Что в наборе ДОЛЖНО быть: таблицы из оглавления дампа и число миграций на
# момент бэкапа (meta.txt пишет backup.sh). Оглавление читает временный
# контейнер — рабочему дамп не передаётся вовсе.
EXPECTED="$(docker exec -i "$TMP_PG" pg_restore --list < "$SET/db.dump" \
  | awk '$4=="TABLE" && $5=="public" {print $6}' | sort -u)"
MIG_SET="$( { grep -oE '^[0-9]+ миграций' "$SET/meta.txt" 2>/dev/null || true; } | grep -oE '^[0-9]+' || true)"

log "Восстановление дампа той же командой, что в restore.sh (займёт несколько минут)…"
T0="$(date +%s)"
RESTORE_ERR="$(mktemp)"
if ! docker exec -i "$TMP_PG" pg_restore -U "$PGUSER" -d "$PGDB" --clean --if-exists \
     < "$SET/db.dump" 2> "$RESTORE_ERR"; then
  MESSAGE="pg_restore завершился с ошибкой: $(tail -1 "$RESTORE_ERR" | tr '"' "'" | cut -c1-200)"
  bad "$MESSAGE"; tail -20 "$RESTORE_ERR" >&2; rm -f "$RESTORE_ERR"; exit 1
fi
rm -f "$RESTORE_ERR"
RESTORE_S=$(( $(date +%s) - T0 ))
log "Восстановлено за ${RESTORE_S} с. Сверка…"

# Точное число строк каждой таблицы — одним запросом в обеих базах.
COUNT_SQL="select table_name, (xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', table_schema, table_name), false, true, '')))[1]::text
           from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE' order by 1"
LIVE_COUNTS="$(mktemp)"; REST_COUNTS="$(mktemp)"; EXP_FILE="$(mktemp)"
docker exec "$LIVE_PG" psql -U "$PGUSER" -d "$PGDB" -tA -F '|' -c "$COUNT_SQL" > "$LIVE_COUNTS"
docker exec "$TMP_PG" psql -U "$PGUSER" -d "$PGDB" -tA -F '|' -c "$COUNT_SQL" > "$REST_COUNTS"
printf '%s\n' "$EXPECTED" | grep -v '^$' > "$EXP_FILE" || true

# Одна строка на таблицу: вид|таблица|рабочая|восстановленная.
#   LOST  — есть в оглавлении дампа, но не восстановилась (набор неполон);
#   NEW   — есть в рабочей базе, в наборе нет (схема ушла вперёд после бэкапа);
#   DIFF  — есть везде, число строк разное; SAME — совпало.
DIFF_REPORT="$(awk -F'|' '
  FILENAME == ARGV[1] { want[$1] = 1; next }
  FILENAME == ARGV[2] { live[$1] = $2; next }
  { rest[$1] = $2 }
  END {
    for (t in want) if (!(t in rest)) print "LOST|" t "|" ((t in live) ? live[t] : "-") "|-";
    for (t in live) {
      if (!(t in rest))            { if (!(t in want)) print "NEW|" t "|" live[t] "|-" }
      else if (live[t] != rest[t]) print "DIFF|" t "|" live[t] "|" rest[t];
      else                         print "SAME|" t "|" live[t] "|" rest[t];
    }
  }' "$EXP_FILE" "$LIVE_COUNTS" "$REST_COUNTS" | sort -t'|' -k2)"
rm -f "$LIVE_COUNTS" "$REST_COUNTS" "$EXP_FILE"

count_kind() { printf '%s\n' "$DIFF_REPORT" | grep -c "^$1|" || true; }
names_of()   { printf '%s\n' "$DIFF_REPORT" | awk -F'|' -v k="$1" '$1==k && n<5 {printf "%s%s", (n ? ", " : ""), $2; n++}'; }
N_EXPECTED="$(printf '%s\n' "$EXPECTED" | grep -c . || true)"
N_REST="$(printf '%s\n' "$DIFF_REPORT" | grep -cE '^(SAME|DIFF)\|' || true)"
N_LOST="$(count_kind LOST)"; N_NEW="$(count_kind NEW)"; N_DIFF="$(count_kind DIFF)"
ROWS="$(printf '%s\n' "$DIFF_REPORT" | awk -F'|' '$1=="SAME"||$1=="DIFF"{s+=$4} END{print s+0}')"

MIG_LIVE="$(docker exec "$LIVE_PG" psql -U "$PGUSER" -d "$PGDB" -tAc "select count(*) from schema_migrations" | tr -d '[:space:]')"
MIG_REST="$(docker exec "$TMP_PG" psql -U "$PGUSER" -d "$PGDB" -tAc "select count(*) from schema_migrations" | tr -d '[:space:]')"

# MinIO: распаковка во временный том и сверка объектов с рабочим томом.
MINIO_LINE="архива MinIO в наборе нет"
MINIO_BAD=""; MINIO_DIFF=""
if [ -f "$SET/minio.tgz" ]; then
  log "Распаковка архива MinIO во временный том…"
  docker volume create "$TMP_VOL" >/dev/null
  if docker run --rm -v "$TMP_VOL":/data -v "$SET_ABS":/backup:ro alpine \
       tar xzf /backup/minio.tgz -C /data; then
    read -r F_REST B_REST <<< "$(docker run --rm -v "$TMP_VOL":/data:ro alpine sh -c "$MINIO_STATS")"
    read -r F_LIVE B_LIVE <<< "$(docker run --rm -v "$MINIO_VOLUME":/data:ro alpine sh -c "$MINIO_STATS")"
    MINIO_LINE="объектов: в рабочем томе $F_LIVE ($(( B_LIVE / 1048576 )) МБ), из архива $F_REST ($(( B_REST / 1048576 )) МБ)"
    if [ "$F_LIVE" != "$F_REST" ] || [ "$B_LIVE" != "$B_REST" ]; then
      MINIO_DIFF=1; MINIO_LINE="$MINIO_LINE — расходится (файлы могли появиться после бэкапа)"
    fi
  else
    MINIO_BAD=1; MINIO_LINE="архив MinIO НЕ распаковался"
  fi
fi

{
  echo "Проверка восстановлением: $(date '+%d.%m.%Y %H:%M')"
  echo "Набор: $SET, образ $IMAGE, восстановлено за ${RESTORE_S} с"
  echo "Таблиц в оглавлении дампа: $N_EXPECTED, восстановлено: $N_REST, строк: $ROWS"
  echo "Миграций: при бэкапе ${MIG_SET:-не записано}, в восстановленной $MIG_REST, в рабочей сейчас $MIG_LIVE"
  echo "MinIO: $MINIO_LINE"
  echo
  echo "   таблица | рабочая | восстановленная   (! — число строк разное, + — появилась после бэкапа, x — НЕ восстановилась)"
  printf '%s\n' "$DIFF_REPORT" | awk -F'|' '{ m = ($1=="SAME") ? "   " : ($1=="DIFF") ? " ! " : ($1=="NEW") ? " + " : " x "; print m $2 " | " $3 " | " $4 }'
} > "$REPORT"

HEAD_MSG="Набор $SET_NAME восстановлен за ${RESTORE_S} с: $(plural "$N_REST" таблица таблицы таблиц), $(plural "$ROWS" строка строки строк), миграций $MIG_REST"

# Набор неполон — это провал: из бэкапа не вернуть то, что в нём должно быть.
FAILS=""
[ "$N_LOST" -gt 0 ] && FAILS="$FAILS; не восстановились таблицы: $N_LOST ($(names_of LOST))"
[ -n "$MIG_SET" ] && [ "$MIG_SET" != "$MIG_REST" ] && FAILS="$FAILS; миграций $MIG_REST, а при бэкапе было $MIG_SET"
[ "$N_EXPECTED" -eq 0 ] && FAILS="$FAILS; в оглавлении дампа нет ни одной таблицы"
[ -n "$MINIO_BAD" ] && FAILS="$FAILS; $MINIO_LINE"
if [ -n "$FAILS" ]; then
  STATUS="fail"
  MESSAGE="Набор $SET_NAME восстановился НЕ полностью${FAILS}"
  bad "$MESSAGE"; echo "Отчёт: $REPORT" >&2
  exit 1
fi

# Набор цел, но рабочая база ушла вперёд — сведения, а не приговор.
AHEAD=""
if [ "$N_NEW" -gt 0 ] || { [ -n "$MIG_LIVE" ] && [ "$MIG_LIVE" != "$MIG_REST" ]; }; then
  AHEAD="$AHEAD; после бэкапа схема ушла вперёд: миграций сейчас $MIG_LIVE"
  [ "$N_NEW" -gt 0 ] && AHEAD="$AHEAD, новые таблицы: $(names_of NEW)"
fi
[ "$N_DIFF" -gt 0 ] && AHEAD="$AHEAD; число строк отличается от рабочей базы в $N_DIFF из $N_REST"
[ -n "$MINIO_DIFF" ] && AHEAD="$AHEAD; MinIO — $MINIO_LINE"

if [ -n "$AHEAD" ]; then
  STATUS="diff"
  MESSAGE="$HEAD_MSG, набор цел${AHEAD}"
  log "$MESSAGE"
  [ "$N_DIFF" -gt 0 ] && printf '%s\n' "$DIFF_REPORT" | awk -F'|' '$1=="DIFF"{ printf "    %s: рабочая %s, восстановленная %s\n", $2, $3, $4 }'
  log "Обычно это записи и изменения, сделанные ПОСЛЕ бэкапа (журналы, входы, файлы, миграции). Отчёт: $REPORT"
  exit 3
fi

STATUS="ok"
MESSAGE="$HEAD_MSG — всё совпало с рабочей базой; MinIO — $MINIO_LINE"
log "$MESSAGE"
log "Отчёт: $REPORT"
