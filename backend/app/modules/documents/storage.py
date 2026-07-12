"""Хранилище документов в MinIO (S3-совместимое)."""
from __future__ import annotations

import io

from minio import Minio

from ...config import settings

_client: Minio | None = None


def get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_user,
            secret_key=settings.minio_password,
            secure=settings.minio_secure,
        )
    return _client


def ensure_bucket() -> None:
    client = get_client()
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)


def put_object(object_name: str, data: bytes, content_type: str) -> str:
    """Загружает байты в бакет; возвращает storage_path (bucket/object)."""
    client = get_client()
    client.put_object(
        settings.minio_bucket,
        object_name,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return f"{settings.minio_bucket}/{object_name}"


def get_object(storage_path: str) -> bytes:
    """Читает объект по storage_path (bucket/object) и возвращает байты."""
    bucket, _, object_name = storage_path.partition("/")
    client = get_client()
    resp = client.get_object(bucket, object_name)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()
