#!/usr/bin/env bash
# ЕДИНЫЙ АВТОУСТАНОВЩИК Dashboard на сервере (Astra Linux / ВМ / LAN, в т.ч. офлайн).
#
# Развёртывание «под ключ» одной командой:
#   tar -xf Final_v.1.tar && cd Dashbord && ./install.sh
#
# Что делает автоматически:
#   1) проверяет Docker и docker compose (сам НЕ ставит — это шаг администратора);
#   2) если рядом лежит офлайн-бандл образов dashbord-images.tar — загружает его
#      (docker load) и деплоит БЕЗ сборки; иначе собирает образы из исходника;
#   3) вызывает deploy.sh, который сам: генерирует секреты (.env.prod), выпускает
#      TLS-сертификат, накатывает миграции, поднимает стек, прогоняет smoke-тест.
#
# Флаги:
#   --no-tls           развернуть по HTTP (без HTTPS-сертификата)
#   прочие флаги и env пробрасываются в deploy.sh (напр. --skip-smoke).
# Сертификат для конкретного сервера: TLS_CN=mfc.local TLS_SAN=10.0.0.5 ./install.sh
set -euo pipefail
cd "$(dirname "$0")"

IMAGES_TAR="dashbord-images.tar"
TLS_FLAG="--tls"
EXTRA=()
for a in "$@"; do
  case "$a" in
    --no-tls) TLS_FLAG="" ;;
    *) EXTRA+=("$a") ;;
  esac
done

log() { printf '\033[1;34m[install]\033[0m %s\n' "$1"; }
err() { printf '\033[1;31m[install] ОШИБКА:\033[0m %s\n' "$1" >&2; }

# 1. Предпосылки: Docker + docker compose v2 + запущенный демон -----------
log "Проверка Docker…"
command -v docker >/dev/null || { err "docker не установлен. Установите Docker Engine + docker-compose-plugin (v2) и повторите."; exit 1; }
docker compose version >/dev/null 2>&1 || { err "нужен docker compose v2 (плагин docker-compose-plugin)."; exit 1; }
docker info >/dev/null 2>&1 || { err "демон Docker недоступен: запущен ли сервис и есть ли права (группа docker / sudo)?"; exit 1; }

# 2. Офлайн-образы: если бандл рядом — загрузить и деплоить без сборки -----
NO_BUILD=""
if [ -f "$IMAGES_TAR" ]; then
  log "Найден офлайн-бандл образов ($IMAGES_TAR) — загружаю в Docker…"
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  tar -xf "$IMAGES_TAR" -C "$tmp"
  if [ -f "$tmp/load.sh" ]; then
    (cd "$tmp" && sh load.sh)
  else
    for t in "$tmp"/*.tar; do [ -f "$t" ] && docker load -i "$t"; done
  fi
  NO_BUILD="--no-build"
  log "Образы загружены — сборка из исходника не потребуется (полный офлайн)."
else
  log "Офлайн-бандл образов не найден → образы соберутся из исходника."
  log "  (для сборки нужен доступ к базовым образам: интернет ИЛИ заранее загруженные postgres/redis/minio)."
fi

# 3. Полный деплой (секреты, TLS, миграции, запуск, smoke — внутри deploy.sh)
log "Запуск deploy.sh${TLS_FLAG:+ $TLS_FLAG}${NO_BUILD:+ $NO_BUILD}…"
./deploy.sh ${TLS_FLAG:-} ${NO_BUILD:-} ${EXTRA[@]+"${EXTRA[@]}"}

log "Установка завершена. Веб-интерфейс и временные пароли — см. вывод выше."
