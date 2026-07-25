"""Конфигурация приложения из переменных окружения."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    # PostgreSQL. По умолчанию — имена сервисов Docker; для локального запуска
    # переопредели через переменные окружения (host=localhost, port=55432).
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "dashbord"
    postgres_user: str = "dashbord"
    postgres_password: str = "dashbord"

    app_name: str = "Dashboard API"
    app_env: str = "dev"

    # Redis (кэш/очереди/фоновый воркер arq). По умолчанию — имя сервиса Docker;
    # для локального запуска: REDIS_HOST=localhost REDIS_PORT=6380
    redis_host: str = "redis"
    redis_port: int = 6379

    # Авторизация
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_minutes: int = 720
    admin_login: str = "admin"
    admin_password: str = "admin"

    # Парольная политика (применяется при смене/сбросе/создании пароля пользователя;
    # НЕ применяется к первичному admin из bootstrap). Настраивается через env.
    password_min_length: int = 8
    password_require_complexity: bool = True  # требовать и буквы, и цифры

    # MinIO (хранилище документов). По умолчанию — имя сервиса Docker;
    # для локального запуска: MINIO_ENDPOINT=localhost:9800
    minio_endpoint: str = "minio:9000"
    minio_user: str = "dashbord"
    minio_password: str = "dashbord123"
    minio_bucket: str = "documents"
    minio_secure: bool = False

    # Жизненный цикл данных (обслуживание, планировщик).
    # Ретенция: скользящее окно хранения данных датасетов (месяцев). 0 — выключено.
    retention_months: int = 12
    # Свежесть: если по объекту нет новых данных дольше N дней — уведомление.
    stale_days: int = 45

    @property
    def database_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
