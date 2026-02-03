"""Файлы пользователя (UserFile) в MinIO и БД."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserFile
from app.services.minio_service import upload_file as minio_upload, delete_file as minio_delete, get_file_url


async def list_user_files(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    limit: int,
    offset: int,
) -> tuple[int, list[UserFile]]:
    from sqlalchemy import func
    count_q = select(func.count()).select_from(UserFile).where(
        UserFile.tenant_id == tenant_id,
        UserFile.user_id == user_id,
    )
    total = (await db.execute(count_q)).scalar() or 0
    q = (
        select(UserFile)
        .where(UserFile.tenant_id == tenant_id, UserFile.user_id == user_id)
        .order_by(UserFile.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(q)
    items = list(result.scalars().all())
    return total, items


async def get_user_file_by_id(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    file_id: UUID,
) -> UserFile | None:
    result = await db.execute(
        select(UserFile).where(
            UserFile.id == file_id,
            UserFile.tenant_id == tenant_id,
            UserFile.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def create_user_file(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    filename: str,
    content_type: str,
    data: bytes,
) -> UserFile:
    minio_key = minio_upload(str(tenant_id), user_id, filename, content_type, data)
    uf = UserFile(
        tenant_id=tenant_id,
        user_id=user_id,
        minio_key=minio_key,
        filename=filename,
        content_type=content_type,
    )
    db.add(uf)
    await db.flush()
    return uf


async def set_file_trigger(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    file_id: UUID,
    trigger: str | None,
) -> UserFile | None:
    uf = await get_user_file_by_id(db, tenant_id, user_id, file_id)
    if not uf:
        return None
    uf.trigger = trigger.strip()[:128] if trigger and trigger.strip() else None
    await db.flush()
    return uf


async def delete_user_file(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    file_id: UUID,
) -> bool:
    uf = await get_user_file_by_id(db, tenant_id, user_id, file_id)
    if not uf:
        return False
    minio_delete(uf.minio_key)
    await db.delete(uf)
    await db.flush()
    return True


def get_presigned_url(minio_key: str, expires: int = 3600) -> str:
    return get_file_url(minio_key, expires_seconds=expires)


async def get_files_with_triggers(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
) -> list[UserFile]:
    result = await db.execute(
        select(UserFile).where(
            UserFile.tenant_id == tenant_id,
            UserFile.user_id == user_id,
            UserFile.trigger.isnot(None),
            UserFile.trigger != "",
        )
    )
    return list(result.scalars().all())


async def get_triggered_files_for_tenant(
    db: AsyncSession,
    tenant_id: UUID,
) -> list[UserFile]:
    """Все файлы с триггерами по тенанту (для клиентского чата)."""
    result = await db.execute(
        select(UserFile).where(
            UserFile.tenant_id == tenant_id,
            UserFile.trigger.isnot(None),
            UserFile.trigger != "",
        )
    )
    return list(result.scalars().all())
