"""Провалившийся бэкап не выглядит свежим (20.09.2026).

Раньше экран брал ПОСЛЕДНИЙ каталог по имени и показывал «Последний:
<сегодня>». Каталог создаётся в начале работы `backup.sh`, поэтому упавший
бэкап оставлял свежую отметку времени и выглядел успешным. Выясняется это в
день аварии, когда восстанавливаться уже не из чего.

Здесь проверяется, что статус отвечает на вопрос «когда мы в последний раз
МОГЛИ БЫ восстановиться», а не «когда что-то писалось на диск».
"""
import re
from pathlib import Path

from app.modules.maintenance import backup_service


def _make_set(root: Path, name: str, *, db: bytes | None = b"PGDMP-x", minio: bool = True,
              failed: str | None = None, part: bool = False) -> Path:
    d = root / name
    d.mkdir(parents=True)
    if db is not None:
        (d / "db.dump").write_bytes(db)
    if part:
        (d / "db.dump.part").write_bytes(b"broken")
    if minio:
        (d / "minio.tgz").write_bytes(b"tgz")
    if failed:
        (d / "FAILED.txt").write_text(failed, encoding="utf-8")
    return d


def test_failed_set_does_not_pass_for_a_fresh_backup(tmp_path, monkeypatch):
    """Свежий провал не подменяет собой последний годный набор."""
    monkeypatch.setattr(backup_service, "BACKUPS_DIR", tmp_path)
    monkeypatch.setattr(backup_service, "TRIGGER_DIR", tmp_path / "ops")
    monkeypatch.setattr(backup_service, "TRIGGER_FILE", tmp_path / "ops" / "backup.request")
    monkeypatch.setattr(backup_service, "RESULT_FILE", tmp_path / "ops" / "backup.result")

    _make_set(tmp_path, "20260913-033000")                      # годный, неделю назад
    _make_set(tmp_path, "20260920-033000", db=None, minio=False,
              failed="Бэкап не завершён, код 1.")               # свежий провал

    st = backup_service.get_status()
    assert st["sets"][0]["name"] == "20260920-033000", "порядок наборов не должен меняться"
    assert st["sets"][0]["ok"] is False
    assert st["last_good"]["name"] == "20260913-033000", \
        "🔴 провалившийся набор снова выдаётся за последний бэкап"
    assert st["failed_since_good"] == 1, "число неудач после годного набора не посчитано"
    assert st["sets"][0]["problem"], "человеку не сказано, что именно не так"


def test_truncated_dump_is_not_a_backup(tmp_path, monkeypatch):
    """Оборванный дамп (остался .part) годным не считается."""
    monkeypatch.setattr(backup_service, "BACKUPS_DIR", tmp_path)
    monkeypatch.setattr(backup_service, "TRIGGER_DIR", tmp_path / "ops")
    monkeypatch.setattr(backup_service, "TRIGGER_FILE", tmp_path / "ops" / "backup.request")
    monkeypatch.setattr(backup_service, "RESULT_FILE", tmp_path / "ops" / "backup.result")

    _make_set(tmp_path, "20260920-033000", db=None, minio=False, part=True)
    st = backup_service.get_status()
    assert st["last_good"] is None
    assert "оборвал" in (st["sets"][0]["problem"] or "").lower()

    # Пустой дамп — тоже не бэкап: при провале редиректом остаётся файл в 0 байт.
    _make_set(tmp_path, "20260919-033000", db=b"")
    st = backup_service.get_status()
    assert st["last_good"] is None, "пустой db.dump принят за годный бэкап"


def test_good_set_stays_good(tmp_path, monkeypatch):
    """Обратная сторона: нормальный набор не должен объявляться сломанным."""
    monkeypatch.setattr(backup_service, "BACKUPS_DIR", tmp_path)
    monkeypatch.setattr(backup_service, "TRIGGER_DIR", tmp_path / "ops")
    monkeypatch.setattr(backup_service, "TRIGGER_FILE", tmp_path / "ops" / "backup.request")
    monkeypatch.setattr(backup_service, "RESULT_FILE", tmp_path / "ops" / "backup.result")

    _make_set(tmp_path, "20260920-033000")
    st = backup_service.get_status()
    assert st["sets"][0]["ok"] is True and st["sets"][0]["problem"] is None
    assert st["last_good"]["name"] == "20260920-033000"
    assert st["failed_since_good"] == 0


def test_script_writes_result_for_every_run_and_is_atomic():
    """Страж по самому backup.sh.

    Три свойства, каждое из которых чинило отдельную беду:
    дамп пишется во временный файл (иначе оборванный `db.dump` выглядит
    готовым); результат пишется при ЛЮБОМ выходе, включая падение (иначе
    плановый бэкап не оставляет следа вовсе); ротация идёт только после
    успеха (иначе неудача вытесняет последнюю годную копию)."""
    # В контейнере тестов файлы поставки смонтированы в /deploy, при локальном
    # прогоне лежат в корне репозитория (тот же приём, что в
    # test_env_template_honest).
    src = next((r / "backup.sh" for r in (Path("/deploy"), Path(__file__).resolve().parents[2])
                if (r / "backup.sh").exists()), None)
    assert src is not None, "backup.sh не найден — тест смотрит не туда"
    text = src.read_text(encoding="utf-8")

    assert "db.dump.part" in text, "дамп снова пишется прямо в db.dump — оборванный файл сойдёт за готовый"
    assert re.search(r'mv "\$DEST/db\.dump\.part" "\$DEST/db\.dump"', text), \
        "переименование после проверки pg_restore пропало"
    assert "trap on_exit EXIT" in text, "результат запуска не пишется при падении"
    assert "write_result true" in text and "write_result false" in text
    assert "FAILED.txt" in text, "провалившийся набор больше не помечается"
    # Ротация обязана остаться ПОСЛЕ проверок: иначе неудачный прогон удалит
    # старые годные наборы, и система останется вовсе без бэкапа. Ищем саму
    # команду удаления, а не слово «Ротация» — оно есть и в шапке скрипта.
    assert text.index("pg_restore --list") < text.index('rm -rf "$old"'), \
        "удаление старых наборов переехало выше проверки дампа"
