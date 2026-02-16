"""Cabinet: dialogs list, dialog detail, saved items, profile."""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dialog, Lead, Message, SavedItem, UserProfile


PREVIEW_MAX_LEN = 120


async def get_tenant_by_slug(db: AsyncSession, slug: str):
    from app.models import Tenant
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    return result.scalar_one_or_none()


async def get_tenant_by_id(db: AsyncSession, tenant_id: UUID):
    from app.models import Tenant
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    return result.scalar_one_or_none()


async def list_dialogs(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    limit: int,
    offset: int,
) -> tuple[int, list]:
    count_q = select(func.count()).select_from(Dialog).where(
        Dialog.tenant_id == tenant_id,
        Dialog.user_id == user_id,
    )
    total = (await db.execute(count_q)).scalar() or 0
    q = (
        select(Dialog)
        .where(Dialog.tenant_id == tenant_id, Dialog.user_id == user_id)
        .order_by(Dialog.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(q)
    dialogs = result.scalars().all()
    items = []
    for d in dialogs:
        preview = None
        msg_q = (
            select(Message.content)
            .where(Message.dialog_id == d.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        msg_result = await db.execute(msg_q)
        row = msg_result.scalar_one_or_none()
        if row:
            preview = (row[0] or "")[:PREVIEW_MAX_LEN] or None
        items.append({"dialog": d, "preview": preview})
    return total, items


async def list_tenant_dialogs(
    db: AsyncSession,
    tenant_id: UUID,
    limit: int,
    offset: int,
) -> tuple[int, list]:
    """Все диалоги тенанта (для админки: диалоги посетителей с ботом через iframe)."""
    count_q = select(func.count()).select_from(Dialog).where(Dialog.tenant_id == tenant_id)
    total = (await db.execute(count_q)).scalar() or 0
    q = (
        select(Dialog)
        .where(Dialog.tenant_id == tenant_id)
        .order_by(Dialog.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(q)
    dialogs = result.scalars().all()
    items = []
    for d in dialogs:
        preview = None
        msg_q = (
            select(Message.content)
            .where(Message.dialog_id == d.id)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        msg_result = await db.execute(msg_q)
        row = msg_result.scalar_one_or_none()
        if row:
            preview = (row[0] or "")[:PREVIEW_MAX_LEN] or None
        items.append({"dialog": d, "preview": preview})
    return total, items


async def get_dialog_messages(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    dialog_id: UUID,
) -> list | None:
    result = await db.execute(
        select(Dialog).where(
            Dialog.id == dialog_id,
            Dialog.tenant_id == tenant_id,
            Dialog.user_id == user_id,
        )
    )
    dialog = result.scalar_one_or_none()
    if not dialog:
        return None
    msg_result = await db.execute(
        select(Message)
        .where(Message.dialog_id == dialog_id, Message.tenant_id == tenant_id)
        .order_by(Message.created_at)
    )
    return list(msg_result.scalars().all())


async def get_dialog_messages_for_tenant(
    db: AsyncSession,
    tenant_id: UUID,
    dialog_id: UUID,
) -> list | None:
    """Сообщения диалога по tenant_id и dialog_id (админ может открыть любой диалог тенанта)."""
    result = await db.execute(
        select(Dialog).where(
            Dialog.id == dialog_id,
            Dialog.tenant_id == tenant_id,
        )
    )
    if not result.scalar_one_or_none():
        return None
    msg_result = await db.execute(
        select(Message)
        .where(Message.dialog_id == dialog_id, Message.tenant_id == tenant_id)
        .order_by(Message.created_at)
    )
    return list(msg_result.scalars().all())


async def list_saved(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    limit: int,
    offset: int,
) -> tuple[int, list]:
    count_q = select(func.count()).select_from(SavedItem).where(
        SavedItem.tenant_id == tenant_id,
        SavedItem.user_id == user_id,
    )
    total = (await db.execute(count_q)).scalar() or 0
    q = (
        select(SavedItem)
        .where(SavedItem.tenant_id == tenant_id, SavedItem.user_id == user_id)
        .order_by(SavedItem.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(q)
    items = list(result.scalars().all())
    return total, items


async def get_saved_by_id(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    saved_id: UUID,
) -> SavedItem | None:
    result = await db.execute(
        select(SavedItem).where(
            SavedItem.id == saved_id,
            SavedItem.tenant_id == tenant_id,
            SavedItem.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_leads(
    db: AsyncSession,
    tenant_id: UUID,
    limit: int,
    offset: int,
) -> tuple[int, list]:
    count_q = select(func.count()).select_from(Lead).where(Lead.tenant_id == tenant_id)
    total = (await db.execute(count_q)).scalar() or 0
    q = (
        select(Lead)
        .where(Lead.tenant_id == tenant_id)
        .order_by(Lead.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(q)
    return total, list(result.scalars().all())


async def get_profile(db: AsyncSession, tenant_id: UUID, user_id: str) -> UserProfile | None:
    result = await db.execute(
        select(UserProfile).where(
            UserProfile.tenant_id == tenant_id,
            UserProfile.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def upsert_profile(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    display_name: str | None = None,
    contact: str | None = None,
) -> UserProfile:
    profile = await get_profile(db, tenant_id, user_id)
    if profile is None:
        profile = UserProfile(tenant_id=tenant_id, user_id=user_id)
        db.add(profile)
        await db.flush()
    if display_name is not None:
        profile.display_name = display_name
    if contact is not None:
        profile.contact = contact
    await db.flush()
    return profile
