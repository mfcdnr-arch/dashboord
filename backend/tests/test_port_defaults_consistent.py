"""Умолчания портов согласованы во всех файлах поставки.

Порт веб-интерфейса по умолчанию записан в семи местах: шаблон .env, два
compose-файла, deploy.sh, smoke.sh, health-watch.sh и diag.sh. Разойдись они —
и отказ тихий: до 24.09.2026 сторож доступности по умолчанию стучался на 8080,
а стек слушал 8090, то есть на установке без явного WEB_PORT в .env.prod сторож
поднимал бы ложную тревогу, а диагностика снимала бы не тот адрес.

Умолчания — стандартные 80/443 (решение заказчика 24.09.2026: адрес набирается
без номера порта).
"""
from __future__ import annotations

import re
from pathlib import Path

_DEPLOY = Path("/deploy")
ROOT = _DEPLOY if (_DEPLOY / "deploy.sh").exists() else Path(__file__).resolve().parents[2]

WEB, HTTPS = "80", "443"


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _shell_defaults(text: str, var: str) -> set[str]:
    """Все умолчания вида VAR="${VAR:-N}" в скрипте."""
    return set(re.findall(rf'{var}="\$\{{{var}:-(\d+)\}}"', text))


def test_template_uses_standard_ports():
    t = _read(".env.prod.example")
    assert re.search(rf"^WEB_PORT={WEB}$", t, re.M)
    assert re.search(rf"^HTTPS_PORT={HTTPS}$", t, re.M)


def test_compose_defaults():
    assert f'"${{WEB_PORT:-{WEB}}}:80"' in _read("docker-compose.prod.yml")
    assert f'"${{HTTPS_PORT:-{HTTPS}}}:443"' in _read("docker-compose.tls.yml")


def test_scripts_share_the_same_defaults():
    for name, needs_https in (("deploy.sh", True), ("health-watch.sh", True), ("diag.sh", True)):
        text = _read(name)
        assert _shell_defaults(text, "WEB_PORT") == {WEB}, f"{name}: WEB_PORT по умолчанию не {WEB}"
        if needs_https:
            assert _shell_defaults(text, "HTTPS_PORT") == {HTTPS}, f"{name}: HTTPS_PORT по умолчанию не {HTTPS}"
    assert 'PORT="${1:-' + WEB + '}"' in _read("smoke.sh")


def test_no_stale_nonstandard_defaults_left():
    """Прежних умолчаний (8090/8443/8080) в ролях умолчания не осталось нигде."""
    for name in ("deploy.sh", "health-watch.sh", "diag.sh", "smoke.sh",
                 "docker-compose.prod.yml", "docker-compose.tls.yml"):
        text = _read(name)
        stale = re.findall(r"(?:WEB_PORT|HTTPS_PORT|PORT):-(8090|8443|8080)", text) + \
            re.findall(r'PORT="\$\{1:-(8090|8443)\}"', text)
        assert not stale, f"{name}: осталось старое умолчание {stale}"


def test_port_check_sees_other_users_sockets():
    """Проверка занятости порта обязана видеть процессы root (apache2/nginx на 80/443).

    lsof без root видит только свои процессы — деплой не остановился бы с
    подсказкой, а упал бы в docker compose с «bind: address already in use».
    """
    d = _read("deploy.sh")
    body = d[d.index("check_port_free() {"): d.index('log "Проверка занятости портов')]
    assert "ss -ltnH" in body
    # Сравниваем проверки наличия команд, а не первые упоминания: слово lsof
    # стоит и в объясняющем комментарии выше кода.
    assert body.index("command -v ss") < body.index("command -v lsof"), "ss должен идти первым, lsof — запасной"
