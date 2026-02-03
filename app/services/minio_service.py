"""MinIO: загрузка и выдача файлов пользователя."""
import io
import uuid
from pathlib import Path

from minio import Minio
from minio.error import S3Error

from app.config import settings


def _client() -> Minio:
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def ensure_bucket() -> None:
    client = _client()
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)


def upload_file(tenant_id: str, user_id: str, filename: str, content_type: str, data: bytes) -> str:
    """Загружает файл в MinIO. Возвращает ключ объекта (minio_key)."""
    ensure_bucket()
    ext = Path(filename).suffix or ""
    key = f"{tenant_id}/{user_id}/{uuid.uuid4()}{ext}"
    client = _client()
    client.put_object(
        settings.minio_bucket,
        key,
        io.BytesIO(data),
        len(data),
        content_type=content_type,
    )
    return key


def get_file_url(key: str, expires_seconds: int = 3600) -> str:
    """Возвращает presigned URL для скачивания/просмотра."""
    client = _client()
    return client.presigned_get_object(settings.minio_bucket, key, expires=expires_seconds)


def delete_file(key: str) -> None:
    client = _client()
    client.remove_object(settings.minio_bucket, key)


def get_file(key: str) -> tuple[bytes, str | None]:
    """Скачивает объект из MinIO. Возвращает (data, content_type)."""
    client = _client()
    response = client.get_object(settings.minio_bucket, key)
    try:
        data = response.read()
        content_type = response.headers.get("Content-Type") if response.headers else None
        return data, content_type
    finally:
        response.close()
        response.release_conn()
