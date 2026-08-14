"""Конфигурация приложения (pydantic-settings).

Все настройки берутся из переменных окружения (см. .env.example).
Не хардкодить секреты — только через Settings.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Окружение ---
    env: Literal["dev", "staging", "prod"] = "dev"
    app_name: str = "price-portal"
    log_level: str = "INFO"
    secret_key: str = Field(default="change-me", min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_ttl_min: int = 15
    refresh_token_ttl_days: int = 7

    # --- БД ---
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_user: str = "price"
    postgres_password: str = "price_secret"
    postgres_db: str = "price_portal"
    db_echo: bool = False  # логировать SQL (dev)

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        """Синхронный URL для Alembic."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # --- Redis / Celery ---
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0
    cache_ttl_seconds: int = 300
    cache_key_prefix: str = "price-portal"

    @property
    def redis_url(self) -> str:
        """Общий Redis URL для API-инфраструктуры (cache/rate limiting)."""
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # --- S3 / MinIO ---
    s3_endpoint: str = "http://minio:9000"
    s3_external_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_region: str = "us-east-1"
    s3_bucket_photos: str = "photos-series"
    s3_bucket_pdfs: str = "pdf-catalogs"
    s3_bucket_exports: str = "csv-exports"
    s3_bucket_tmp: str = "tmp-uploads"
    s3_bucket_errors: str = "error-logs"
    s3_presign_ttl_seconds: int = 300  # время жизни presigned-URL (§10: 5 мин)

    # --- Импорт CSV (§7) ---
    import_max_file_mb: int = 100  # верхний предел загрузки прайс-листа
    import_allowed_extensions: str = ".csv,.txt"  # регистронезависимо

    @property
    def import_allowed_ext_list(self) -> list[str]:
        return [e.strip().lower() for e in self.import_allowed_extensions.split(",") if e.strip()]

    # --- Валюты / НБ РБ ---
    nbrb_rates_url: str = "https://www.nbrb.by/api/exrates/rates"
    nbrb_fetch_cron: str = "5 0 * * *"  # ежедневно 00:05 (Europe/Minsk)
    base_currency: str = "BYN"
    display_currencies: str = "BYN,USD,EUR,RUB"

    @property
    def display_currency_list(self) -> list[str]:
        return [c.strip().upper() for c in self.display_currencies.split(",") if c.strip()]

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_manager_chat_id: str = ""
    telegram_webhook_url: str = ""

    # --- 1С интеграция (заглушки) ---
    integration_1c_token: str = ""
    integration_1c_ip_allowlist: str = ""

    # --- Security / CORS ---
    rate_limit_login: str = "5/15minutes"
    csrf_cookie_name: str = "csrf_token"
    csrf_header_name: str = "X-CSRF-Token"
    cors_origins: str = "http://localhost:3000,http://localhost:8080"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @field_validator("env")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
