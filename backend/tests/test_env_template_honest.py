"""Шаблон .env.prod.example не обещает того, чего система не сделает.

Дефект, ради которого заведён тест (аудит 14.09): в шаблоне стояло
«RETENTION_MONTHS=12  # 0 — выключить прунинг», но переменная не пробрасывалась
в контейнер ни одним compose-файлом. Администратор ставил 0, перезапускал стек
и считал, что исторические отчёты в безопасности, — а планировщик каждое
воскресенье продолжал удалять выпуски старше 12 месяцев вместе со значениями
каскадом. Необратимая потеря данных, вызванная не ошибкой админа, а неверной
документацией шаблона.

Правило, которое здесь закрепляется: каждая переменная прикладного уровня из
шаблона обязана либо доезжать до контейнера, либо не стоять в шаблоне вовсе.
Пороги, у которых есть экран в «Настройках», хранятся в БД и побеждают env —
поэтому их в шаблоне быть не должно: env там молча ничего не делает.

Тест читает сами файлы поставки — как test_widget_registry_consistency читает
исходники фронта. Он не запускает приложение и не ходит в БД."""
import re
from pathlib import Path

# В контейнере смонтирован только backend/, поэтому файлы поставки лежат
# в /deploy (см. docker-compose.yml, сервис tests); при локальном прогоне из
# дерева репозитория они на своих местах в корне.
_ROOTS = [Path("/deploy"), Path(__file__).resolve().parents[2]]
ROOT = next((r for r in _ROOTS if (r / ".env.prod.example").exists()), _ROOTS[-1])
TEMPLATE = ROOT / ".env.prod.example"
COMPOSE = [ROOT / "docker-compose.prod.yml", ROOT / "docker-compose.tls.yml",
           ROOT / "docker-compose.monitoring.yml"]
# Исходники приложения смонтированы отдельно и всегда доступны как /app/app.
APP = Path("/app/app") if Path("/app/app").exists() else Path(__file__).resolve().parents[1] / "app"

# Переменные инфраструктуры: их читают сами compose/скрипты развёртывания, а не
# приложение, поэтому в environment контейнера им делать нечего.
INFRA = {
    "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_PORT",
    "MINIO_USER", "MINIO_PASSWORD", "MINIO_API_PORT", "MINIO_CONSOLE_PORT",
    "REDIS_PORT", "WEB_PORT", "HTTPS_PORT", "API_PORT",
    "TLS_CN", "TLS_SAN",
    "BACKUP_TIME", "BACKUP_KEEP", "BACKUP_DIR",
    "GRAFANA_PORT", "GRAFANA_USER", "GRAFANA_PASSWORD", "PROMETHEUS_PORT",
    "LOKI_PORT", "COMPOSE_PROJECT_NAME",
}
# Пины образов — тоже инфраструктура (подстановка в image:).
INFRA_PREFIXES = ("IMAGE_", "PIN_")
INFRA_SUFFIXES = ("_IMAGE", "_TAG", "_VERSION")

# Пороги с экраном в «Настройках»: хранятся в БД, значение из БД побеждает env.
# Их присутствие в шаблоне — обман, даже если пробросить.
UI_MANAGED = {"RETENTION_MONTHS", "STALE_DAYS", "LOGIN_MAX_ATTEMPTS",
              "LOGIN_LOCKOUT_MINUTES", "APPEAL_RESPONSE_HOURS"}


def _declared() -> set:
    """Переменные, объявленные в шаблоне (закомментированные — тоже обещание)."""
    out = set()
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", line)
        if m:
            out.add(m.group(1))
    return out


def _passed_to_container() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in COMPOSE if p.exists())


def _is_infra(name: str) -> bool:
    return (name in INFRA or name.startswith(INFRA_PREFIXES)
            or name.endswith(INFRA_SUFFIXES))


def test_every_app_variable_reaches_the_container():
    """Прикладная переменная из шаблона обязана доезжать до приложения."""
    compose = _passed_to_container()
    missing = [n for n in sorted(_declared())
               if not _is_infra(n) and f"${{{n}" not in compose]
    assert not missing, (
        "Объявлены в .env.prod.example, но не пробрасываются ни одним compose-файлом "
        f"— администратор правит их впустую: {missing}")


def test_ui_managed_thresholds_are_not_promised_in_the_template():
    """Порог, у которого есть экран, не должен стоять в .env.

    Значение из БД побеждает, поэтому переменная молча не работала бы —
    ровно тот обман, из-за которого терялись данные."""
    declared = _declared()
    wrong = sorted(UI_MANAGED & declared)
    assert not wrong, (
        "Эти пороги настраиваются в «Настройках» и хранятся в БД; в шаблоне они "
        f"вводят администратора в заблуждение: {wrong}")


def test_password_policy_is_actually_wired():
    """Обратная сторона: у парольной политики экрана НЕТ, поэтому она обязана
    и стоять в шаблоне, и доезжать до контейнера."""
    declared, compose = _declared(), _passed_to_container()
    for name in ("PASSWORD_MIN_LENGTH", "PASSWORD_REQUIRE_COMPLEXITY"):
        assert name in declared, f"{name} пропал из шаблона, а экрана у него нет"
        assert f"${{{name}" in compose, f"{name} объявлен, но не доезжает до приложения"


def test_zero_disables_retention_in_code():
    """Ноль действительно выключает удаление — иначе шаблон обещал бы
    несуществующее поведение уже на уровне кода."""
    src = (APP / "modules/maintenance/service.py").read_text(encoding="utf-8")
    assert "if not m or m <= 0:" in src, (
        "В run_retention пропала проверка на ноль: «0 — выключить» перестало работать")
