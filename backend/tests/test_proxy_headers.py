"""Nginx обязан давать журналам настоящий адрес клиента (страж к находке 4.8).

Адрес в журнале аудита и журнале входов берётся из `X-Real-IP`, потому что
`proxy_set_header` ПЕРЕЗАПИСЫВАЕТ присланное клиентом. Если эту строку убрать
или заменить `$proxy_add_x_forwarded_for` на `$http_x_forwarded_for`, подделка
вернётся МОЛЧА: приложение по-прежнему будет писать адрес, просто снова тот,
что выбрал клиент. Поэтому конфигурацию поставки проверяем тестом — тем же
приёмом, каким `test_env_template_honest` читает шаблон .env.

Второй инвариант здесь — «правило одно»: разбор заголовков живёт только в
app/clientip.py. Копия правила в другом модуле однажды разошлась бы с
оригиналом, а именно из-за копии дефект и пришлось чинить в двух местах.
"""
import ast
import re
from pathlib import Path

import yaml

# Каталог frontend/ смонтирован в контейнер тестов как /frontend (см.
# docker-compose.yml, сервис tests); при локальном прогоне — в дереве репозитория.
_ROOTS = [Path("/frontend"), Path(__file__).resolve().parents[2] / "frontend"]
FRONT = next((r for r in _ROOTS if (r / "nginx.locations.conf").exists()), _ROOTS[-1])
CONFS = ["nginx.locations.conf", "nginx.conf", "nginx.tls.conf"]
APP = Path("/app/app") if Path("/app/app").exists() else Path(__file__).resolve().parents[1] / "app"
# Файлы поставки — в /deploy внутри контейнера тестов (см. docker-compose.yml).
_DEPLOY = [Path("/deploy"), Path(__file__).resolve().parents[2]]
DEPLOY = next((r for r in _DEPLOY if (r / "docker-compose.prod.yml").exists()), _DEPLOY[-1])
PROD_COMPOSE = ["docker-compose.prod.yml", "docker-compose.tls.yml", "docker-compose.monitoring.yml"]

REAL_IP = "proxy_set_header X-Real-IP $remote_addr;"
FORWARDED = "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;"


def _proxy_blocks() -> list[tuple[str, str, str]]:
    """Блоки `location`, проксирующие на API: (файл, заголовок блока, тело)."""
    out = []
    for name in CONFS:
        path = FRONT / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"^\s*location[^\n{]*\{", text, re.M):
            depth, i = 0, m.end() - 1
            while i < len(text):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            body = text[m.end():i]
            if "proxy_pass" in body:
                out.append((name, m.group(0).strip(), body))
    return out


def test_every_api_location_hands_over_the_real_address():
    """У каждого проксирующего блока есть X-Real-IP — источник адреса журналов."""
    blocks = _proxy_blocks()
    assert blocks, f"в {FRONT} не найдено ни одного location с proxy_pass — разбор конфига сломан"
    for name, head, body in blocks:
        assert REAL_IP in body, (
            f"{name}: в блоке «{head}» нет «{REAL_IP}» — журнал начнёт писать адрес, "
            f"выбранный клиентом (находка аудита 4.8)")


def test_forwarded_for_is_appended_by_nginx_not_passed_through():
    """Список дописывается, а не пробрасывается: приложение читает его ПОСЛЕДНИЙ
    элемент как адрес от доверенного прокси. С `$http_x_forwarded_for` последним
    оказалось бы то, что прислал клиент."""
    for name, head, body in _proxy_blocks():
        assert FORWARDED in body, f"{name}: в блоке «{head}» нет «{FORWARDED}»"
        assert "$http_x_forwarded_for" not in body, (
            f"{name}: блок «{head}» пробрасывает заголовок клиента как есть — "
            f"хвост списка перестанет быть адресом от nginx")


def test_both_server_configs_include_the_single_locations_file():
    """HTTP и HTTPS берут один и тот же список маршрутов: иначе заголовки
    разойдутся между вариантами развёртывания."""
    for name in ("nginx.conf", "nginx.tls.conf"):
        text = (FRONT / name).read_text(encoding="utf-8")
        assert "dashbord-locations.conf" in text, f"{name} не включает общий файл маршрутов"


def test_header_parsing_lives_only_in_clientip():
    """Разбор заголовков адреса — в одном модуле. Вторая копия правила и была
    причиной того, что подделку пришлось чинить в двух местах сразу.

    Смотрим на строковые литералы КОДА, а не на текст файла: назвать заголовок
    в комментарии или в пояснении к настройке — нормально, а вот прочитать его
    своим кодом мимо clientip — нет.
    """
    guilty = []
    for path in APP.rglob("*.py"):
        if path.name == "clientip.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                first = (node.body or [None])[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                        and isinstance(first.value.value, str):
                    docs.add(id(first.value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                low = node.value.lower()
                if "x-forwarded-for" in low or "x-real-ip" in low:
                    guilty.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert not guilty, (
        "заголовки адреса разбираются вне app/clientip.py: " + ", ".join(guilty) +
        " — правило должно быть одно на оба журнала")


def test_api_port_is_not_published_outside():
    """Наружу опубликован только веб-контейнер — в API приходят через nginx.

    На это опирается умолчание доверия (приватные сети и loopback): адрес
    контейнера nginx заранее неизвестен, поэтому доверяем диапазону. Опубликуй
    кто-нибудь порт api — и доверие приватным сетям начнёт работать против нас:
    подделать адрес в журнале сможет любой, кто дотянется до порта из LAN.
    Тогда `TRUSTED_PROXIES` придётся сузить до адреса прокси явно.
    """
    for name in PROD_COMPOSE:
        path = DEPLOY / name
        if not path.exists():
            continue
        services = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("services") or {}
        ports = (services.get("api") or {}).get("ports")
        assert not ports, (
            f"{name}: сервису api опубликован порт {ports} — в API можно прийти мимо nginx, "
            f"и доверие приватным сетям в app/clientip.py перестаёт быть безопасным; "
            f"либо уберите публикацию, либо сузьте TRUSTED_PROXIES до адреса прокси")
