"""Проверка бэкапа восстановлением (restore-check.sh) — поведение самого скрипта.

Скрипт запускается на БОЕВОМ сервере рядом с рабочей базой, и цена ошибки в нём
несимметрична: перепутай он контейнер — `pg_restore --clean` снёс бы рабочие
данные тем самым бэкапом, который проверяет. Поэтому главное, что здесь держим:
восстановление идёт ТОЛЬКО во временный контейнер, рабочая база только читается,
а временная убирается при любом исходе — вместе с томом данных.

Вместо docker в PATH — заглушка: пишет вызовы в файл и отвечает по сценарию.
Проверяем, ЧТО скрипт решил сделать, а не что он напечатал (приём test_worker_guard).
Сам скрипт копируется во временный каталог: он читает .env.prod рядом с собой,
и так его можно проверить с разными настройками, не трогая файлы поставки.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

_DEPLOY = Path("/deploy")
ROOT = _DEPLOY if (_DEPLOY / "restore-check.sh").exists() else Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "restore-check.sh"

LIVE = "dashbord_prod_postgres"
TMP = "dashbord_restorecheck_pg"
TMP_PGDATA = "dashbord_restorecheck_pgdata"
TMP_MINIO = "dashbord_restorecheck_minio"

STUB = r"""#!/usr/bin/env bash
echo "$*" >> "$CALLS"
case "$*" in
  "inspect -f {{.Config.Image}} "*) [ -n "${STUB_IMAGE_FAIL:-}" ] && exit 1; echo postgres:16-alpine ;;
  "inspect "*)          exit 0 ;;
  "info "*)             echo "$STUB_ROOT" ;;
  *pg_database_size*)   echo "${STUB_DB_MB:-10}" ;;
  "run -d "*)           echo tmpid ;;
  *"select 1"*)         exit 0 ;;
  # Оглавление дампа — раньше общего *pg_restore*: иначе ушло бы в ветку восстановления.
  *"pg_restore --list"*) cat > /dev/null
                        for t in $STUB_TOC; do
                          echo "1; 1259 1 TABLE public $t dashbord"
                          echo "2; 0 1 TABLE DATA public $t dashbord"
                        done ;;
  *pg_restore*)         cat > /dev/null
                        if [ "${STUB_RESTORE:-ok}" != ok ]; then
                          echo 'pg_restore: error: could not execute query:' \
                               'ERROR:  role "x" does not exist' >&2
                          exit 1
                        fi ;;
  *"exec $STUB_LIVE"*information_schema*) printf '%b' "$STUB_LIVE_COUNTS" ;;
  *"exec $STUB_TMP"*information_schema*)  printf '%b' "$STUB_REST_COUNTS" ;;
  *"exec $STUB_LIVE"*schema_migrations*)  echo "${STUB_MIG_LIVE:-56}" ;;
  *"exec $STUB_TMP"*schema_migrations*)   echo "${STUB_MIG_REST:-56}" ;;
  *"$STUB_TMPVOL":/data:ro*)  echo "${STUB_MINIO_REST:-10 1048576}" ;;
  *"$STUB_LIVEVOL":/data:ro*) echo "${STUB_MINIO_LIVE:-10 1048576}" ;;
esac
exit 0
"""

TABLES = "audit_log dataset_values schema_migrations users"
COUNTS = "audit_log|11\ndataset_values|3672775\nschema_migrations|56\nusers|4\n"


def run_check(tmp_path: Path, sets: dict[str, dict] | None = None, arg: str | None = None,
              env_file: str | None = None, backup_dir_env: bool = True, **env):
    """Прогнать restore-check.sh с подставным docker.

    sets — наборы: имя → {"dump", "failed", "minio", "meta", "mtime"}.
    Возвращает (результат, вызовы docker, каталог триггеров, каталог бэкапов).
    """
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    shutil.copy(SCRIPT, work / "restore-check.sh")
    if env_file is not None:
        (work / ".env.prod").write_text(env_file)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "docker").write_text(STUB)
    (bin_dir / "docker").chmod(0o755)
    calls = tmp_path / "calls.txt"
    calls.write_text("")
    trig = tmp_path / "ops-triggers"
    backups = tmp_path / "backups"
    backups.mkdir(exist_ok=True)
    for i, (name, opt) in enumerate((sets if sets is not None else {"20260924-030000": {}}).items()):
        d = backups / name
        d.mkdir(exist_ok=True)
        if opt.get("dump", True):
            (d / "db.dump").write_bytes(b"PGDMP-fake")
        if opt.get("minio", True):
            (d / "minio.tgz").write_bytes(b"fake")
        if opt.get("failed"):
            (d / "FAILED.txt").write_text("x")
        if opt.get("meta", True):
            (d / "meta.txt").write_text(f"created_at={name}\npg_db=dashbord\n{opt.get('mig', 56)} миграций\n")
        t = opt.get("mtime", time.time() - 1000 + i * 10)
        os.utime(d, (t, t))

    e = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CALLS": str(calls),
        "OPS_TRIGGER_DIR": str(trig),
        "RC_POLL_SEC": "0",
        "STUB_ROOT": str(tmp_path),
        "STUB_LIVE": LIVE,
        "STUB_TMP": TMP,
        "STUB_LIVEVOL": "dashbord-prod_miniodata",
        "STUB_TMPVOL": TMP_MINIO,
        "STUB_TOC": TABLES,
        "STUB_LIVE_COUNTS": COUNTS,
        "STUB_REST_COUNTS": COUNTS,
        **{k: str(v) for k, v in env.items()},
    }
    e.pop("BACKUP_DIR", None)
    if backup_dir_env:
        e["BACKUP_DIR"] = str(backups)
    cmd = ["bash", str(work / "restore-check.sh")] + ([arg] if arg else [])
    p = subprocess.run(cmd, capture_output=True, text=True, env=e, timeout=60)
    return p, calls.read_text().splitlines(), trig, backups


def result(trig: Path) -> dict:
    return json.loads((trig / "restore-check.result").read_text())


def restores(calls: list[str]) -> list[str]:
    return [c for c in calls if "pg_restore" in c and "--list" not in c]


def test_vosstanovlenie_tolko_vo_vremennuyu_bazu(tmp_path):
    """Главное: pg_restore идёт во временный контейнер, рабочая база не получает его НИКОГДА."""
    p, calls, trig, _ = run_check(tmp_path)
    assert p.returncode == 0, p.stdout + p.stderr
    assert len(restores(calls)) == 1
    assert restores(calls)[0].startswith(f"exec -i {TMP} pg_restore"), restores(calls)
    assert not any(LIVE in c and "pg_restore" in c for c in calls), "pg_restore в рабочую базу!"
    # Рабочая база только читается: к ней — лишь psql-запросы.
    live_calls = [c for c in calls if f"exec {LIVE}" in c or f"exec -i {LIVE}" in c]
    assert live_calls and all(" psql " in c for c in live_calls), live_calls
    # Временная база без сети, с лимитами и с ИМЕНОВАННЫМ томом данных.
    run = next(c for c in calls if c.startswith("run -d"))
    assert "--network none" in run and "--memory" in run and "--cpus" in run
    assert f"-v {TMP_PGDATA}:/var/lib/postgresql/data" in run, run
    r = result(trig)
    assert r["ok"] is True and r["status"] == "ok"
    assert "совпало" in r["message"]


def test_vremennaya_baza_ubiraetsya_vmeste_s_tomom(tmp_path):
    """Временная база весит как рабочая. Без удаления ТОМА `docker rm -f` оставлял бы
    на диске полную копию боевой базы после каждого прогона (находка ревью 24.09)."""
    p, calls, trig, _ = run_check(tmp_path, STUB_RESTORE="fail")
    assert p.returncode == 1
    assert calls[-3:] == [f"rm -f -v {TMP}", f"volume rm -f {TMP_PGDATA}", f"volume rm -f {TMP_MINIO}"], calls[-4:]
    assert not (trig / "restore-check.lock").exists(), "замок остался — следующий запуск откажет"
    r = result(trig)
    assert r["ok"] is False
    assert "pg_restore" in r["message"] and "role" in r["message"], r["message"]


def test_rashozhdenie_nazvano_chislami(tmp_path):
    """Число строк разошлось — код 3 и точные числа по каждой таблице, а не «что-то не так»."""
    p, calls, trig, _ = run_check(
        tmp_path, STUB_REST_COUNTS=COUNTS.replace("audit_log|11", "audit_log|10"),
    )
    assert p.returncode == 3, p.stdout + p.stderr
    assert "audit_log: рабочая 11, восстановленная 10" in p.stdout
    r = result(trig)
    assert r["status"] == "diff" and r["ok"] is True
    assert "в 1 из 4" in r["message"], r["message"]


def test_ne_vosstanovivshayasya_tablica_eto_proval(tmp_path):
    """Таблица есть в оглавлении дампа, но не восстановилась — негодный бэкап, а не «расхождение»."""
    p, calls, trig, _ = run_check(
        tmp_path, STUB_REST_COUNTS=COUNTS.replace("users|4\n", ""),
    )
    assert p.returncode == 1
    r = result(trig)
    assert r["ok"] is False and "не восстановились таблицы: 1 (users)" in r["message"], r["message"]


def test_bekap_do_migracii_ne_obyavlyaetsya_negodnym(tmp_path):
    """deploy.sh бэкапит ДО миграций. Таблица, появившаяся после бэкапа, — сведения
    (код 3), а не провал: иначе первая же проверка после обновления кричала бы
    «бэкап негоден» про исправный набор (находка ревью 24.09)."""
    p, calls, trig, _ = run_check(
        tmp_path,
        STUB_LIVE_COUNTS=COUNTS + "object_layout_template_history|0\n",
        STUB_MIG_LIVE="57",
    )
    assert p.returncode == 3, p.stdout + p.stderr
    r = result(trig)
    assert r["ok"] is True and r["status"] == "diff"
    assert "схема ушла вперёд: миграций сейчас 57" in r["message"], r["message"]
    assert "object_layout_template_history" in r["message"]


def test_migracii_sveryayutsya_s_naborom(tmp_path):
    """Миграций в восстановленной базе меньше, чем было при бэкапе (meta.txt), — набор неполон."""
    p, calls, trig, _ = run_check(tmp_path, STUB_MIG_REST="55")
    assert p.returncode == 1
    assert "миграций 55, а при бэкапе было 56" in result(trig)["message"]


def test_otchet_ne_trogaet_kataloga_nabora(tmp_path):
    """Отчёт пишется в ops-triggers: запись в каталог набора сдвигала бы время его
    изменения — по нему работают ротация и отметка «Последний успешный бэкап»."""
    stamp = time.time() - 5 * 86400
    p, calls, trig, backups = run_check(tmp_path, sets={"20260919-030000": {"mtime": stamp}})
    assert p.returncode == 0, p.stdout + p.stderr
    assert (trig / "restore-check.txt").exists()
    assert not (backups / "20260919-030000" / "restore-check.txt").exists()
    assert abs((backups / "20260919-030000").stat().st_mtime - stamp) < 1


def test_beryotsya_posledniy_godnyy_nabor_po_imeni(tmp_path):
    """Выбор — по имени (это время бэкапа), а не по mtime; провалившийся и недописанный пропускаются."""
    now = time.time()
    sets = {
        "20260921-030000": {"mtime": now - 100},               # годный, но mtime «свежее» всех
        "20260922-030000": {"mtime": now - 900},               # годный, самый поздний по имени
        "20260923-030000": {"failed": True, "mtime": now - 800},
        "20260924-030000": {"dump": False, "mtime": now - 700},
    }
    p, calls, trig, backups = run_check(tmp_path, sets=sets)
    assert p.returncode == 0, p.stdout + p.stderr
    assert result(trig)["set"] == "20260922-030000"


def test_katalog_iz_env_prod(tmp_path):
    """BACKUP_DIR из .env.prod — как у backup-schedule.sh: иначе при бэкапах на отдельном
    диске проверялся бы старый набор из ./backups, а ночные — никогда."""
    nightly = tmp_path / "nightly"
    (nightly / "20260924-033000").mkdir(parents=True)
    (nightly / "20260924-033000" / "db.dump").write_bytes(b"x")
    (nightly / "20260924-033000" / "meta.txt").write_text("56 миграций\n")
    p, calls, trig, _ = run_check(tmp_path, env_file=f"BACKUP_DIR={nightly}\n", backup_dir_env=False)
    assert p.returncode in (0, 3), p.stdout + p.stderr
    assert result(trig)["set"] == "20260924-033000"


def test_pustoy_katalog_ponyatnyy_otkaz(tmp_path):
    """Наборов нет вовсе — подсказка сделать бэкап, а не кусок исходника со «Сбоем»."""
    p, calls, trig, _ = run_check(tmp_path, sets={})
    assert p.returncode == 1
    assert "Сначала ./backup.sh" in p.stderr, p.stderr
    assert restores(calls) == []


def test_nabor_bez_dampa_ponyatnyy_otkaz(tmp_path):
    p, calls, trig, _ = run_check(tmp_path, sets={"20260924-030000": {"dump": False}})
    assert p.returncode == 1
    assert "Сначала ./backup.sh" in p.stderr
    assert restores(calls) == []


def test_nehvatka_mesta_ostanavlivaet_do_zapuska(tmp_path):
    """Места на вторую копию базы нет — останавливаемся ДО временной базы, а не заполняем диск."""
    p, calls, trig, _ = run_check(tmp_path, STUB_DB_MB="999999999")
    assert p.returncode == 1
    assert not any(c.startswith("run -d") for c in calls)
    assert restores(calls) == []
    assert "Мало места" in result(trig)["message"]


def test_neozhidannyy_sboy_nazyvaet_sebya(tmp_path):
    """Непредвиденный сбой обязан сказать, где упал. Первый прогон на стенде молча
    написал «Проверка прервана» — df по невидимому с хоста пути оборвал set -e."""
    p, calls, trig, _ = run_check(tmp_path, STUB_IMAGE_FAIL="1")
    assert p.returncode != 0
    msg = result(trig)["message"]
    assert "Сбой на строке" in msg and "Config.Image" in msg, msg


def test_minio_rashozhdenie_ne_proval(tmp_path):
    """Файлы MinIO после бэкапа появляются законно — это расхождение (3), а не провал."""
    p, calls, trig, _ = run_check(tmp_path, STUB_MINIO_LIVE="12 2097152")
    assert p.returncode == 3, p.stdout + p.stderr
    assert "MinIO" in result(trig)["message"]
