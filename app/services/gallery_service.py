"""Галереи изображений пользователя."""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Gallery, GalleryItem, UserFile


async def list_galleries(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
) -> list[Gallery]:
    result = await db.execute(
        select(Gallery).where(
            Gallery.tenant_id == tenant_id,
            Gallery.user_id == user_id,
        ).order_by(Gallery.created_at.desc())
    )
    return list(result.scalars().all())


async def get_gallery_by_id(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    gallery_id: UUID,
) -> Gallery | None:
    result = await db.execute(
        select(Gallery).where(
            Gallery.id == gallery_id,
            Gallery.tenant_id == tenant_id,
            Gallery.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def create_gallery(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    name: str,
) -> Gallery:
    g = Gallery(tenant_id=tenant_id, user_id=user_id, name=name)
    db.add(g)
    await db.flush()
    return g


async def delete_gallery(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    gallery_id: UUID,
) -> bool:
    g = await get_gallery_by_id(db, tenant_id, user_id, gallery_id)
    if not g:
        return False
    await db.delete(g)
    await db.flush()
    return True


async def add_file_to_gallery(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    gallery_id: UUID,
    user_file_id: UUID,
) -> GalleryItem | None:
    from app.services.file_service import get_user_file_by_id
    g = await get_gallery_by_id(db, tenant_id, user_id, gallery_id)
    if not g:
        return None
    uf = await get_user_file_by_id(db, tenant_id, user_id, user_file_id)
    if not uf:
        return None
    max_pos = await db.execute(
        select(func.coalesce(func.max(GalleryItem.position), -1)).where(GalleryItem.gallery_id == gallery_id)
    )
    pos = (max_pos.scalar() or 0) + 1
    item = GalleryItem(gallery_id=gallery_id, user_file_id=user_file_id, position=pos)
    db.add(item)
    await db.flush()
    return item


async def remove_from_gallery(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    gallery_id: UUID,
    item_id: UUID,
) -> bool:
    g = await get_gallery_by_id(db, tenant_id, user_id, gallery_id)
    if not g:
        return False
    result = await db.execute(
        select(GalleryItem).where(
            GalleryItem.id == item_id,
            GalleryItem.gallery_id == gallery_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        return False
    await db.delete(item)
    await db.flush()
    return True
