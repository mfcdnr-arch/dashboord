#!/usr/bin/env bash
# Генерация самоподписанного TLS-сертификата для HTTPS в ЛОКАЛЬНОЙ СЕТИ (LAN,
# без публичного DNS/Let's Encrypt). Для гос-он-прем этого достаточно; браузеры
# покажут предупреждение о самоподписанном сертификате (можно добавить свой CA в
# доверенные на клиентах).
#
#   ./gen-tls.sh                     # CN=localhost, SAN=localhost,127.0.0.1
#   ./gen-tls.sh mfc.local 10.0.0.5  # CN + доп. SAN (hostname/IP сервера в LAN)
#
# Результат: certs/tls.crt, certs/tls.key (срок 825 дней). Идемпотентно: если
# сертификат уже есть — не перезаписывает (перевыпуск: удалите файлы).
set -euo pipefail
cd "$(dirname "$0")"

CN="${1:-localhost}"
EXTRA_SAN="${2:-}"
DIR="certs"
CRT="$DIR/tls.crt"
KEY="$DIR/tls.key"

log() { printf '\033[1;34m[tls]\033[0m %s\n' "$1"; }
command -v openssl >/dev/null || { echo "нужен openssl"; exit 1; }

if [ -f "$CRT" ] && [ -f "$KEY" ]; then
  log "Сертификат уже существует ($CRT) — не трогаю. Для перевыпуска удалите certs/."
  exit 0
fi

mkdir -p "$DIR"

# Список SAN: localhost + 127.0.0.1 + (если задан) hostname/IP сервера.
SAN="DNS:localhost,IP:127.0.0.1"
if [ -n "$EXTRA_SAN" ]; then
  if printf '%s' "$EXTRA_SAN" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
    SAN="$SAN,IP:$EXTRA_SAN"
  else
    SAN="$SAN,DNS:$EXTRA_SAN"
  fi
fi
[ "$CN" != "localhost" ] && SAN="$SAN,DNS:$CN"

log "Выпуск самоподписанного сертификата: CN=$CN, SAN=$SAN (825 дней)…"
openssl req -x509 -newkey rsa:2048 -sha256 -days 825 -nodes \
  -keyout "$KEY" -out "$CRT" \
  -subj "/O=GBU MFC DNR/CN=$CN" \
  -addext "subjectAltName=$SAN" 2>/dev/null

chmod 600 "$KEY"; chmod 644 "$CRT"
log "Готово: $CRT + $KEY. Подключается через docker-compose.tls.yml (deploy.sh --tls)."
