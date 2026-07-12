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

    # Авторизация
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_minutes: int = 720
    admin_login: str = "admin"
    admin_password: str = "admin"

    # MinIO (хранилище документов). По умолчанию — имя сервиса Docker;
    # для локального запуска: MINIO_ENDPOINT=localhost:9800
    minio_endpoint: str = "minio:9000"
    minio_user: str = "dashbord"
    minio_password: str = "dashbord123"
    minio_bucket: str = "documents"
    minio_secure: bool = False

    @property
    def database_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
