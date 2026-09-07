"""S3 / MinIO хранилище (sync-клиент boto3).

См. ARCHITECTURE_PLAN.md §10 (бакеты), §7.2 (пайплайн импорта).

Используется:
  * эндпоинтом загрузки CSV — ``upload_fileobj`` (стримингом) в бакет
    ``tmp-uploads``;
  * Celery-задачей импорта — ``get_bytes`` исходника и ``put_bytes`` отчёта
    ошибок в ``error-logs``;
  * запросом статуса — ``presigned_get`` для выдачи менеджеру ссылки на отчёт.

Sync-клиент выбран намеренно: Celery-задача sync, а FastAPI-эндпоинт зовёт
storage-функции через ``run_in_threadpool`` (event loop не блокируется).
Для асинхронной обёртки (aioboto3) пока нет нужды: boto3 сам стримит
file-like объекты частями (multipart), не материализуя их в памяти.
"""
from __future__ import annotations

from functools import lru_cache

import boto3
from botocore.client import BaseClient, Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("app.services.storage")


class StorageError(RuntimeError):
    """Ошибка хранилища S3 (network / доступ / отстутствие объекта)."""


@lru_cache(maxsize=1)
def get_s3_client() -> BaseClient:
    """Синглтон S3-клиента (endpoint — внутреннее имя MinIO в compose).

    Таймауты и лимит ретраев обязательны: без них сетевая неполадка MinIO
    подвешивает вызывающего (Celery-воркер / API-поток) на botocore-дефолты
    (60 с connect, бесконечные ретраи).
    """
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=10,
            read_timeout=15,
            retries={"max_attempts": 2},
        ),
    )


@lru_cache(maxsize=1)
def get_s3_presign_client() -> BaseClient:
    """Клиент для генерации presigned-URL.

    Host входит в SigV4-подпись (SignedHeaders), поэтому подписываем ТЕМ
    host, который MinIO реально видит в запросе. На проде nginx-виртуалхост
    статики (managed хостера, ``proxy_set_header Host`` недоступен) форвардит
    upstream'у Host ``127.0.0.1:19000`` (proxy_host), а не внешний. Поэтому
    подпись считается на внутренний endpoint (``s3_endpoint``), а в готовой
    строке URL хост строково заменяется на внешний (``s3_external_endpoint``)
    — браузер идёт на внешний адрес, nginx проксирует на MinIO с Host,
    под которым считалась подпись. Замена хоста после генерации подпись НЕ
    ломает: SigV4 фиксирует host на момент подписания.
    ``generate_presigned_url`` не делает сетевых запросов.
    """
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def put_bytes(
    bucket: str, key: str, data: bytes, *, content_type: str = "application/octet-stream"
) -> None:
    """Загрузить ``data`` в ``bucket/key``. Перебои сети → :class:`StorageError`."""
    client = get_s3_client()
    try:
        client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    except (BotoCoreError, ClientError) as exc:
        log.warning("s3.put_failed", bucket=bucket, key=key, error=str(exc))
        raise StorageError(f"Не удалось загрузить объект {bucket}/{key}") from exc


def upload_fileobj(
    bucket: str, key: str, fileobj, *, content_type: str = "application/octet-stream"
) -> None:
    """Загрузить file-like объект стримингом (multipart, буфер — одна часть).

    Файл не читается в память целиком: boto3 TransferManager сам читает
    ``fileobj`` частями по 8 МБ. Перебои сети → :class:`StorageError`.
    """
    client = get_s3_client()
    try:
        client.upload_fileobj(
            fileobj, bucket, key, ExtraArgs={"ContentType": content_type}
        )
    except (BotoCoreError, ClientError) as exc:
        log.warning("s3.upload_fileobj_failed", bucket=bucket, key=key, error=str(exc))
        raise StorageError(f"Не удалось загрузить объект {bucket}/{key}") from exc


def get_bytes(bucket: str, key: str) -> bytes:
    """Прочитать объект целиком как bytes. Отсутствие → :class:`StorageError`."""
    client = get_s3_client()
    try:
        resp = client.get_object(Bucket=bucket, Key=key)
    except (BotoCoreError, ClientError) as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        log.warning("s3.get_failed", bucket=bucket, key=key, code=code, error=str(exc))
        raise StorageError(f"Не удалось прочитать объект {bucket}/{key}") from exc
    return resp["Body"].read()


def delete_object(bucket: str, key: str) -> None:
    """Удалить объект из ``bucket``. Перебои сети → :class:`StorageError`.

    S3 ``DeleteObject`` идемпотентен: отсутствие объекта — не ошибка
    (204), поэтому «best effort»-удаление достаточно (§16 п.18).
    """
    client = get_s3_client()
    try:
        client.delete_object(Bucket=bucket, Key=key)
    except (BotoCoreError, ClientError) as exc:
        log.warning("s3.delete_failed", bucket=bucket, key=key, error=str(exc))
        raise StorageError(f"Не удалось удалить объект {bucket}/{key}") from exc


def presigned_get(bucket: str, key: str, *, expires: int | None = None) -> str:
    """Presigned URL на чтение объекта (TTL из настроек, по умолчанию 5 мин).

    Используется браузером: подпись считается на внутренний endpoint (см.
    ``get_s3_presign_client`` — nginx форвардит upstream'у внутренний Host),
    затем в строке URL хост заменяется на внешний (``s3_external_endpoint``),
    чтобы ссылка была валидна снаружи контейнера.
    """
    client = get_s3_presign_client()
    ttl = expires if expires is not None else settings.s3_presign_ttl_seconds
    try:
        url = client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=ttl
        )
    except (BotoCoreError, ClientError) as exc:
        log.warning("s3.presign_failed", bucket=bucket, key=key, error=str(exc))
        raise StorageError(f"Не удалось создать ссылку на {bucket}/{key}") from exc
    if settings.s3_external_endpoint:
        url = url.replace(settings.s3_endpoint, settings.s3_external_endpoint, 1)
    return url


# ----------------------------- readiness (/readyz) -----------------------------

@lru_cache(maxsize=1)
def get_s3_health_client() -> BaseClient:
    """Клиент для readiness-проб: короткие таймауты и без ретраев —
    проверка не должна подвешивать /readyz (1-2 с на компоненту)."""
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=2,
            read_timeout=2,
            retries={"max_attempts": 1},
        ),
    )


def check_connection() -> None:
    """Живость MinIO для /readyz: ``head_bucket`` бакета выгрузок.

    Сетевые функции клиента здесь не важны — нужна лишь доступность S3.
    Ошибка → :class:`StorageError` (readyz мапит её в «s3: fail»).
    """
    bucket = settings.s3_bucket_exports
    try:
        get_s3_health_client().head_bucket(Bucket=bucket)
    except (BotoCoreError, ClientError) as exc:
        log.warning("s3.head_bucket_failed", bucket=bucket, error=str(exc))
        raise StorageError(f"Хранилище S3 недоступно: {exc}") from exc
