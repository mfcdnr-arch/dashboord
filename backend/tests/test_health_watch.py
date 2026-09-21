"""Сторож доступности — единственный сигнал, уходящий НАРУЖУ.

Почему тест гоняет САМ bash-скрипт. Всё, что система сообщает о своём
состоянии, она пишет внутрь себя; ровно в том случае, ради которого сигнал и
нужен, экран, где его было бы видно, и есть то, что не открывается. Поэтому
сторож живёт на хосте, и проверять тут нечего, кроме его настоящего поведения.

Ошибки здесь дорогие и обе тихие: промолчит — авария останется незамеченной,
закричит не по делу — сигнал перестанут читать, и он не сработает в настоящий
раз. Поэтому проверяются не только отказы, но и МОЛЧАНИЕ там, где кричать не о
чем: одиночная осечка, повтор уже объявленной тревоги, обслуживание.

Вместо системы поднимается крошечный HTTP-сервер, отвечающий по сценарию.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

_DEPLOY = Path("/deploy")
ROOT = _DEPLOY if (_DEPLOY / "health-watch.sh").exists() else Path(__file__).resolve().parents[2]
WATCH = ROOT / "health-watch.sh"

# Пропуска по отсутствию файла НЕТ намеренно: скрипт — часть поставки, и его
# исчезновение это регрессия, а не повод молча сделать набор зелёным.


class _Handler(BaseHTTPRequestHandler):
    scenario = "ok"

    def do_GET(self):
        if self.scenario == "ok":
            code, body = 200, b'{"status":"ok","db":"ok","worker":"ok"}'
        elif self.scenario == "degraded":
            code, body = 200, b'{"status":"degraded","db":"unavailable","worker":"unknown"}'
        elif self.scenario == "spa":  # ответил веб-прокси, а не приложение
            code, body = 200, b"<!doctype html><html><body>SPA</body></html>"
        else:
            code, body = 502, b"Bad Gateway"
        self.send_response(code)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def run(tmp_path: Path, url: str, **env) -> Path:
    """Один прогон сторожа. Возвращает каталог триггеров."""
    ops = tmp_path / "ops"
    ops.mkdir(exist_ok=True)
    e = dict(os.environ, OPS_TRIGGER_DIR=str(ops), HEALTH_URL=url, HEALTH_INTERVAL="0")
    e.update({k: str(v) for k, v in env.items()})
    r = subprocess.run(["bash", str(WATCH)], cwd=str(ROOT), env=e,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"сторож завершился с ошибкой: {r.stderr[:400]}"
    return ops


def state(ops: Path) -> tuple[str, str]:
    lines = (ops / "health.state").read_text().splitlines()
    return lines[0], (lines[2] if len(lines) > 2 else "")


def transitions(ops: Path) -> list[str]:
    log = ops / "health.log"
    return log.read_text().splitlines() if log.exists() else []


def test_alarm_only_after_several_failures(tmp_path, server):
    """Одиночная осечка — не авария.

    Сеть моргает, прокси перезапускается, сервер занят. Сигнал, поднимающий
    дежурного зря, перестают читать — и тогда он не сработает в настоящий раз.
    """
    dead = "http://127.0.0.1:9/health"  # порт discard: соединения нет
    ops = run(tmp_path, dead)
    assert state(ops)[0] == "down" and not transitions(ops), "закричал с первой осечки"
    run(tmp_path, dead)
    assert not transitions(ops), "закричал со второй осечки"

    ops = run(tmp_path, dead)
    assert state(ops)[0] == "alarm"
    assert len(transitions(ops)) == 1, transitions(ops)
    assert "недоступна" in transitions(ops)[0]

    # Повтор уже объявленной тревоги — молчание: иначе каждые пять минут
    # приходило бы одно и то же, и в этом потоке потерялось бы всё остальное.
    run(tmp_path, dead)
    assert len(transitions(ops)) == 1, "тревога объявлена повторно"


def test_recovery_is_announced_once(tmp_path, server):
    """О возврате в строй сообщаем — но только если до этого кричали.

    Иначе красная отметка висела бы вечно и читалась как незакрытая авария, а
    зелёная строка каждые пять минут превратила бы журнал в шум.
    """
    dead = "http://127.0.0.1:9/health"
    live = f"http://127.0.0.1:{server.server_address[1]}/health"
    _Handler.scenario = "ok"

    for _ in range(3):
        ops = run(tmp_path, dead)
    assert state(ops)[0] == "alarm"

    ops = run(tmp_path, live)
    assert state(ops)[0] == "ok"
    assert [t.split("\t")[1] for t in transitions(ops)] == ["alarm", "recovery"]

    run(tmp_path, live)
    assert len(transitions(ops)) == 2, "о работающей системе сообщили второй раз"


@pytest.mark.parametrize("scenario,expect", [
    ("degraded", "база данных недоступна"),
    ("spa", "отвечает не приложение"),
    ("bad", "веб-прокси отвечает ошибкой"),
])
def test_causes_are_distinguished(tmp_path, server, scenario, expect):
    """За каждым исходом своя починка — сваливать их в одно нельзя.

    «Отвечает, но база недоступна» → чинят Postgres. «На /health отвечает не
    приложение» → сломана маршрутизация веб-прокси, и это НЕ про базу: именно
    так выглядит запрос, провалившийся в SPA-fallback (журнал 10.08). Первая
    версия сторожа называла этот случай отказом базы — правдоподобно и неверно;
    найдено живой проверкой, а не рассуждением.
    """
    _Handler.scenario = scenario
    url = f"http://127.0.0.1:{server.server_address[1]}/health"
    for _ in range(3):
        ops = run(tmp_path, url)
    assert state(ops)[0] == "alarm"
    assert expect in state(ops)[1], state(ops)


def test_maintenance_pause_silences_the_watch(tmp_path, server):
    """На время обновления сторож молчит — иначе КАЖДЫЙ деплой поднимал бы тревогу.

    Паузу ставит deploy.sh и снимает при любом выходе, включая ошибку.
    """
    ops = tmp_path / "ops"
    ops.mkdir()
    (ops / "health-watch.off").write_text("")
    run(tmp_path, "http://127.0.0.1:9/health")
    assert not (ops / "health.state").exists(), "проверка выполнялась во время обслуживания"
    assert (ops / "health.fails").read_text().strip() == "0", \
        "счётчик осечек не сброшен: первая проверка после деплоя добила бы порог"


def test_probe_is_throttled(tmp_path, server):
    """Зовут раз в минуту, спрашиваем раз в пять — шаг задаёт сам сторож.

    Отдельный таймер не заводили намеренно: на уже развёрнутых серверах его
    пришлось бы ставить руками. Значит, частоту нельзя отдавать вызывающему.
    """
    _Handler.scenario = "ok"
    live = f"http://127.0.0.1:{server.server_address[1]}/health"
    ops = run(tmp_path, live, HEALTH_INTERVAL=300)
    stamp = (ops / "health.last").read_text()
    run(tmp_path, "http://127.0.0.1:9/health", HEALTH_INTERVAL=300)
    assert (ops / "health.last").read_text() == stamp, "проверил раньше срока"
    assert state(ops)[0] == "ok", "состояние изменилось, хотя проверки не было"


def test_watch_is_wired_into_the_minute_watcher():
    """Сторож должен вызываться ИЗ ops-trigger-watch.sh и ДО его выхода.

    Тот завершается по отсутствию заявки на бэкап в подавляющем большинстве
    запусков — вызов ниже этой строки не выполнился бы никогда. На этих самых
    граблях уже стоял сторож воркера.
    """
    text = (ROOT / "ops-trigger-watch.sh").read_text()
    pos_watch = text.find("health-watch.sh")
    pos_exit = text.find('[ -f "$REQUEST" ] || exit 0')
    assert pos_watch > 0, "сторож доступности не вызывается из минутного наблюдателя"
    assert pos_exit > 0 and pos_watch < pos_exit, \
        "вызов стоит ПОСЛЕ выхода по отсутствию заявки — не выполнится никогда"


def test_deploy_pauses_and_always_releases():
    """deploy.sh ставит паузу и снимает её через trap.

    Без trap неудачный деплой оставил бы сторожа выключенным навсегда, и
    падение после него осталось бы незамеченным — тихий отказ защиты от тихих
    отказов, худшее, что тут можно построить.
    """
    lines = (ROOT / "deploy.sh").read_text().splitlines()
    var = next((ln.split("=", 1)[0].strip() for ln in lines
                if "health-watch.off" in ln and "=" in ln.split("#")[0]), None)
    assert var, "деплой не глушит сторожа на время обновления"
    traps = [ln for ln in lines if ln.strip().startswith("trap ") and "EXIT" in ln]
    assert any(f"${var}" in ln or f"${{{var}}}" in ln for ln in traps), \
        f"пауза ({var}) снимается не через trap EXIT — при ошибке деплоя останется навсегда"
