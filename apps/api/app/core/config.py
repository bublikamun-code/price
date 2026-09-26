"""Конфигурация приложения (pydantic-settings).

Все настройки берутся из переменных окружения (см. .env.example).
Не хардкодить секреты — только через Settings.
"""
import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, PrivateAttr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


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
    secret_key: str = Field(min_length=16)
    jwt_algorithm: str = "HS256"
    # RS256 (prod, §16 п.15): пути к PEM-файлам, смонтированным read-only
    # (пару ключей создаёт `make gen-jwt-keys` → infra/jwt-keys/)
    jwt_private_key_path: str | None = None
    jwt_public_key_path: str | None = None
    access_token_ttl_min: int = 15
    refresh_token_ttl_days: int = 7

    # Кэш PEM-ключей по пути: файл читается один раз, а не на каждый запрос (§16 п.15)
    _jwt_pem_cache: dict[str, str] = PrivateAttr(default_factory=dict)

    def _read_pem(self, path: str) -> str:
        """PEM-содержимое файла с кэшем по пути.

        Потокобезопасно: запись в dict атомарна под GIL, гонка даёт лишь
        повторное чтение того же файла — результат идемпотентен.
        """
        pem = self._jwt_pem_cache.get(path)
        if pem is None:
            pem = Path(path).read_text(encoding="utf-8")
            self._jwt_pem_cache[path] = pem
        return pem

    @property
    def jwt_signing_key(self) -> str:
        """Ключ подписи JWT: HS256 → SECRET_KEY, RS256 → приватный PEM (§16 п.15)."""
        if self.jwt_algorithm == "RS256":
            return self._read_pem(self.jwt_private_key_path)
        return self.secret_key

    @property
    def jwt_verify_key(self) -> str:
        """Ключ проверки JWT: HS256 → SECRET_KEY, RS256 → публичный PEM (§16 п.15)."""
        if self.jwt_algorithm == "RS256":
            return self._read_pem(self.jwt_public_key_path)
        return self.secret_key

    # --- БД ---
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_user: str = "price"
    postgres_password: str = Field(min_length=1)
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

    # --- Observability (§12, §16 п.23) ---
    # Pushgateway для Celery-метрик. Пусто = push выключен (fail-open, только debug-лог).
    # В overlay infra/docker-compose.observability.yml: PUSHGATEWAY_URL=http://pushgateway:9091
    pushgateway_url: str = ""

    # --- S3 / MinIO ---
    s3_endpoint: str = "http://minio:9000"
    s3_external_endpoint: str = "http://localhost:9000"
    s3_access_key: str = Field(min_length=1)
    s3_secret_key: str = Field(min_length=1)
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

    # --- Файловый архив (§16 п.18) ---
    files_max_mb: int = 200  # лимит загрузки файла в архив (pdf-catalogs)

    # --- PDF-выгрузки (§16 п.25) ---
    pdf_supplier_name: str = "ООО «Поставщик»"  # шапка PDF-заявки (блок «Поставщик»)

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

    # --- Email / SMTP ---
    # Пустой SMTP_HOST → сервис письма не отправляет (no-op: рендерится текст и
    # пишется в лог INFO). Ссылка сброса пароля строится от WEB_APP_URL.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    web_app_url: str = ""                # напр. https://portal.example.by
    manager_notify_email: str = ""       # пусто → письмо о новой заявке не шлём
    smtp_tls: bool = True                # STARTTLS после connect (SMTP_TLS=0 → без TLS, напр. локальный mailhog)

    @property
    def password_reset_ttl_min(self) -> int:
        return 30

    # --- Telegram ---
    telegram_bot_token: str = ""
    telegram_manager_chat_id: str = ""
    telegram_webhook_url: str = ""

    # --- 1С интеграция (заглушки) ---
    integration_1c_token: str = ""
    integration_1c_ip_allowlist: str = ""

    # --- Security / CORS ---
    rate_limit_login: str = "5/15minutes"
    # Лимит на запрос сброса пароля (forgot-password) — по IP.
    rate_limit_forgot_password: str = "5/15minutes"
    # Блокировка аккаунта после N неудачных входов (§16 п.21, H4):
    # попыток до блокировки и длительность блокировки (минуты).
    login_max_attempts: int = 5
    login_lockout_minutes: int = 30
    # Второй шаг логина при 2FA — тот же лимит, что у login (§16 п.22)
    rate_limit_2fa_verify: str = "5/15minutes"
    # Ticket второго шага логина при 2FA: JWT type=2fa, TTL 5 мин (§16 п.22)
    totp_ticket_ttl_min: int = 5
    csrf_cookie_name: str = "csrf_token"
    csrf_header_name: str = "X-CSRF-Token"
    # Флаг Secure у кук аутентификации (access/refresh/csrf): prod — true,
    # куки уходят только по HTTPS (COOKIE_SECURE=true в prod-compose, §16 п.30)
    cookie_secure: bool = False
    # Grace-окно ротации refresh-токена (сек, аудит P0-1): старый токен после
    # ротации принимается в пределах окна — параллельные refresh (несколько
    # вкладок) не рвут сессию; после окна — обычный 401 (reuse-detection).
    refresh_grace_seconds: int = 60
    # CSP в enforcing-режиме (§16 п.30): браузер блокирует нарушения политики.
    # 'unsafe-inline' в script/style — для инлайн-скриптов гидратации Nuxt SSR.
    # Пустая строка = заголовок выключен.
    content_security_policy: str = (
        "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'self'; form-action 'self'"
    )
    # Токен доступа к /metrics. Пусто в dev/staging — ручка отдаётся как
    # раньше. В prod пустой токен закрывает ручку в 404 (как /docs), иначе
    # метрики были бы доступны всем, кто достал URL.
    metrics_token: str = ""
    # HSTS отдаётся только на https-запросах. max-age намеренно короткий:
    # сайт на shared-хостинге с auto-SSL хостера, и годовой HSTS заблокирует
    # быстрый откат, если сертификат протухнет. Поднимать до года — после
    # того как автопродление подтверждено.
    hsts_max_age: int = 86400
    # Функции браузера, которые портал не использует. Пусто = заголовок выключен.
    permissions_policy: str = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    cors_origins: str = "http://localhost:3000,http://localhost:8080"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @field_validator("env")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()

    @model_validator(mode="after")
    def _check_jwt_keys(self) -> "Settings":
        """RS256 требует PEM-ключи из файлов — проверяем на старте, fail fast (§16 п.15)."""
        if self.jwt_algorithm not in ("HS256", "RS256"):
            # опечатка в алгоритме молча уводила бы подпись в HS256-ветку
            raise ValueError(
                f"JWT_ALGORITHM: допустимы только HS256 и RS256, получено {self.jwt_algorithm!r}"
            )
        if self.jwt_algorithm == "RS256":
            if not self.jwt_private_key_path or not self.jwt_public_key_path:
                raise ValueError(
                    "JWT_ALGORITHM=RS256: обязательны JWT_PRIVATE_KEY_PATH и "
                    "JWT_PUBLIC_KEY_PATH (пару ключей создаст `make gen-jwt-keys`)"
                )
            for name, path in (
                ("JWT_PRIVATE_KEY_PATH", self.jwt_private_key_path),
                ("JWT_PUBLIC_KEY_PATH", self.jwt_public_key_path),
            ):
                try:
                    Path(path).read_text(encoding="utf-8")
                except OSError as exc:
                    raise ValueError(f"{name}={path}: файл не найден или не читается ({exc})") from exc
        elif self.jwt_algorithm == "HS256" and (self.jwt_private_key_path or self.jwt_public_key_path):
            logger.warning(
                "Заданы JWT_*_KEY_PATH при JWT_ALGORITHM=HS256 — PEM-ключи не используются (§16 п.15)"
            )
        return self

    @model_validator(mode="after")
    def _check_prod_security(self) -> "Settings":
        """Продовые инварианты безопасности проверяем на старте, fail fast."""
        if self.env != "prod":
            return self

        errors: list[str] = []
        if not self.cookie_secure:
            errors.append("COOKIE_SECURE=true")
        if self.jwt_algorithm != "RS256":
            errors.append("JWT_ALGORITHM=RS256")
        if any(
            "localhost" in origin.lower() or "127.0.0.1" in origin.lower()
            for origin in self.cors_origin_list
        ):
            errors.append("CORS_ORIGINS без localhost/127.0.0.1")
        if self.secret_key == "change-me-to-a-long-random-string" or len(self.secret_key) < 32:
            errors.append("SECRET_KEY не должен быть дефолтным или короче 32 символов")

        if errors:
            raise ValueError("Некорректные продовые настройки безопасности: " + "; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
