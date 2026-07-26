#!/usr/bin/env bash
# Авто-генерация .env.prod с СИЛЬНЫМИ случайными секретами (для развёртывания на
# реальном сервере без ручного придумывания паролей).
#
#   ./gen-secrets.sh            # создать .env.prod, если его нет
#   ./gen-secrets.sh --force    # пересоздать (перезапишет секреты!)
#
# Значения секретов берутся из openssl rand. ADMIN/SUPERADMIN пароли — временные
# (система потребует сменить при первом входе); печатаются ОДИН РАЗ здесь.
set -euo pipefail
cd "$(dirname "$0")"

FORCE=""
[ "${1:-}" = "--force" ] && FORCE=1

log() { printf '\033[1;34m[secrets]\033[0m %s\n' "$1"; }
err() { printf '\033[1;31m[secrets] ОШИБКА:\033[0m %s\n' "$1" >&2; }

command -v openssl >/dev/null || { err "нужен openssl"; exit 1; }
[ -f .env.prod.example ] || { err "нет .env.prod.example рядом со скриптом"; exit 1; }

if [ -f .env.prod ] && [ -z "$FORCE" ]; then
  if grep -q "CHANGE_ME" .env.prod; then
    err ".env.prod уже есть, но содержит CHANGE_ME. Запустите с --force для пересоздания или заполните вручную."
    exit 1
  fi
  log ".env.prod уже существует и заполнен — ничего не делаю (idempotent). --force для пересоздания."
  exit 0
fi

# Генераторы: пароли — base64 без спецсимволов, ломающих .env; JWT — длинный hex.
pw()  { openssl rand -base64 24 | tr -d '/+=' | cut -c1-24; }
jwt() { openssl rand -hex 48; }

POSTGRES_PASSWORD="$(pw)"
MINIO_PASSWORD="$(pw)"
JWT_SECRET="$(jwt)"
ADMIN_PASSWORD="$(pw)"
SUPERADMIN_PASSWORD="$(pw)"
GRAFANA_PASSWORD="$(pw)"

# Берём шаблон и подставляем секреты (строки KEY=CHANGE_ME...).
cp .env.prod.example .env.prod
set_kv() {  # set_kv KEY VALUE  — заменяет строку KEY=... целиком
  local key="$1" val="$2"
  # экранируем & и | для sed
  local esc; esc="$(printf '%s' "$val" | sed -e 's/[&|]/\\&/g')"
  if grep -qE "^${key}=" .env.prod; then
    sed -i.bak -E "s|^${key}=.*|${key}=${esc}|" .env.prod && rm -f .env.prod.bak
  else
    printf '%s=%s\n' "$key" "$val" >> .env.prod
  fi
}

set_kv POSTGRES_PASSWORD "$POSTGRES_PASSWORD"
set_kv MINIO_PASSWORD "$MINIO_PASSWORD"
set_kv JWT_SECRET "$JWT_SECRET"
set_kv ADMIN_PASSWORD "$ADMIN_PASSWORD"
set_kv SUPERADMIN_PASSWORD "$SUPERADMIN_PASSWORD"
set_kv GRAFANA_PASSWORD "$GRAFANA_PASSWORD"

chmod 600 .env.prod

if grep -q "CHANGE_ME" .env.prod; then
  err "в .env.prod остались CHANGE_ME (появились новые ключи в шаблоне?). Проверьте вручную."; exit 1
fi

log "Создан .env.prod (права 600) с сильными случайными секретами."
echo
echo "  ┌─ ВРЕМЕННЫЕ ПАРОЛИ ВХОДА (запишите — показаны один раз, смена при 1-м входе) ─┐"
printf "  │  admin       : %s\n" "$ADMIN_PASSWORD"
printf "  │  superadmin  : %s\n" "$SUPERADMIN_PASSWORD"
echo "  └──────────────────────────────────────────────────────────────────────────────┘"
echo
log "Секреты БД/MinIO/JWT сгенерированы и лежат в .env.prod (наружу не показываются)."
