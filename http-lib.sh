#!/usr/bin/env bash
# Минимальный HTTP-клиент для скриптов развёртывания: curl, а если его нет — python3.
#
# Зачем: в базовой Astra Linux НЕТ ни curl, ни wget (проверено на боевом сервере
# заказчика 06.08.2026 — установка прошла полностью, но deploy.sh упал на
# ожидании веб-прокси с «curl: команда не найдена», а smoke дал три ✗ подряд;
# со стороны выглядело как провалившееся развёртывание, хотя стек работал).
# python3 в Astra есть всегда, поэтому установка «одной командой на чистом
# сервере» больше не зависит от наличия curl.
#
# Использование (source ./http-lib.sh):
#   http_client_available        — есть ли чем ходить по HTTP
#   http_code URL [TIMEOUT]      — код ответа на stdout ('000', если соединения нет)
#   http_body URL [TIMEOUT]      — тело на stdout; ненулевой код возврата при HTTP >= 400
#
# Сертификат не проверяется (в LAN он самоподписанный — проверяем доступность
# сервиса, а не доверие к УЦ; ровно так же вёл себя прежний `curl -k`).

# Клиент можно задать заранее (HTTP_CLIENT=python3 ./deploy.sh …) — пригодно и
# для проверки питоновской ветки на машине, где curl есть, и на случай, если
# curl в системе сломан.
if [ -z "${HTTP_CLIENT:-}" ]; then
  HTTP_CLIENT=""
  if command -v curl >/dev/null 2>&1; then
    HTTP_CLIENT="curl"
  elif command -v python3 >/dev/null 2>&1; then
    HTTP_CLIENT="python3"
  fi
fi

http_client_available() { [ -n "$HTTP_CLIENT" ]; }

# Питоновская реализация. r.getcode() вместо r.status — работает и на python 3.7
# (Astra 1.7 основана на Debian 10), тогда как .status появился только в 3.9.
_http_py() { # $1 url, $2 timeout, $3 mode: code|body
  python3 - "$1" "$2" "$3" <<'PY'
import ssl
import sys
import urllib.error
import urllib.request

url, timeout, mode = sys.argv[1], float(sys.argv[2]), sys.argv[3]
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

code, body = 0, b""
try:
    with urllib.request.urlopen(url, timeout=timeout, context=ctx) as r:
        code, body = r.getcode(), r.read()
except urllib.error.HTTPError as e:          # 4xx/5xx — это ответ, а не сбой связи
    code, body = e.code, e.read()
except Exception:                            # нет соединения/таймаут/DNS
    pass

if mode == "code":
    print("%03d" % code)
else:
    sys.stdout.buffer.write(body)
    sys.exit(0 if 200 <= code < 400 else 1)
PY
}

http_code() { # URL [TIMEOUT] → код ответа
  local url="$1" t="${2:-10}"
  if [ "$HTTP_CLIENT" = "curl" ]; then
    # При сбое соединения curl сам печатает 000 и выходит ненулевым — гасим код
    # возврата, чтобы вызывающая сторона получила именно '000' на stdout.
    curl -ks -o /dev/null -w '%{http_code}' -m "$t" "$url" 2>/dev/null || true
  else
    _http_py "$url" "$t" code
  fi
}

http_body() { # URL [TIMEOUT] → тело; ненулевой код возврата при ошибке HTTP
  local url="$1" t="${2:-10}"
  if [ "$HTTP_CLIENT" = "curl" ]; then
    curl -ksf -m "$t" "$url"
  else
    _http_py "$url" "$t" body
  fi
}
