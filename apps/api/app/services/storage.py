"""S3 / MinIO хранилище (sync-клиент boto3).

См. ARCHITECTURE_PLAN.md §10 (бакеты), §7.2 (пайплайн импорта).

Используется:
  * эндпоинтом загрузки CSV — ``put_bytes`` в бакет ``tmp-uploads``;
  * Celery-задачей импорта — ``get_bytes`` исходника и ``put_bytes`` отчёта
    ошибок в ``error-logs``;
  * запросом статуса — ``presigned_get`` для выдачи менеджеру ссылки на отчёт.

Sync-клиент выбран намеренно: Celery-задача sync, а FastAPI-эндпоинт читает
поток ``UploadFile`` тоже синхронно (через ``read()``). Для асинхронной
обёртки (aioboto3) пока нет нужды — объёмы загрузок небольшие (≤100 МБ).
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
    """Синглтон S3-клиента (endpoint — внутреннее имя MinIO в compose)."""
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


def presigned_get(bucket: str, key: str, *, expires: int | None = None) -> str:
    """Presigned URL на чтение объекта (TTL из настроек, по умолчанию 5 мин).

    Используется браузером: host берётся из ``s3_external_endpoint``,
    поэтому ссылка доступна снаружи контейнера.
    """
    client = get_s3_client()
    ttl = expires if expires is not None else settings.s3_presign_ttl_seconds
    try:
        # generate_presigned_url сам подставит s3_external_endpoint только если
        # клиент создан с ним; мы создаём клиент на внутренний endpoint, поэтому
        # генерируем ссылку и переписываем хост на внешний.
        url = client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=ttl
        )
    except (BotoCoreError, ClientError) as exc:
        log.warning("s3.presign_failed", bucket=bucket, key=key, error=str(exc))
        raise StorageError(f"Не удалось создать ссылку на {bucket}/{key}") from exc
    return _rewrite_host_to_external(url)


def _rewrite_host_to_external(url: str) -> str:
    """Заменить внутренний хост MinIO на внешний (доступный браузеру)."""
    internal = settings.s3_endpoint
    external = settings.s3_external_endpoint
    if internal and external and url.startswith(internal):
        return external + url[len(internal):]
    return url
