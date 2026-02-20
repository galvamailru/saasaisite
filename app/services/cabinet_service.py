"""Cabinet: dialogs list, dialog detail, saved items, profile."""
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dialog, Lead, McpServer, Message, SavedItem, UserProfile


PREVIEW_MAX_LEN = 120


async def get_tenant_by_slug(db: AsyncSession, slug: str):
    from app.models import Tenant
    result = await db.execute(select(Tenant).where(Tenant.slug == slug))
    return result.scalar_one_or_none()


async def get_tenant_by_id(db: AsyncSession, tenant_id: UUID):
    from app.models import Tenant
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    return result.scalar_one_or_none()


async def get_first_confirmed_user_of_tenant(db: AsyncSession, tenant_id: UUID):
    """Первый подтверждённый пользователь тенанта (для входа администратора в кабинет тенанта)."""
    from app.models import TenantUser
    result = await db.execute(
        select(TenantUser)
        .where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.email_confirmed_at.isnot(None),
        )
        .order_by(TenantUser.created_at)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_all_tenants(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
) -> tuple[int, list]:
    """Список тенантов с пагинацией и поиском по slug/названию (для страницы «Пользователи»). Возвращает (total, list)."""
    from app.models import Tenant
    condition = True
    if search and search.strip():
        term = "%" + search.strip() + "%"
        condition = or_(
            Tenant.slug.ilike(term),
            Tenant.name.ilike(term),
        )
    count_q = select(func.count()).select_from(Tenant).where(condition)
    total = (await db.execute(count_q)).scalar() or 0
    q = select(Tenant).where(condition).order_by(Tenant.slug).limit(limit).offset(offset)
    result = await db.execute(q)
    return total, list(result.scalars().all())


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
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[int, list]:
    """Все диалоги тенанта. date_from/date_to — фильтр по updated_at (включительно)."""
    count_q = select(func.count()).select_from(Dialog).where(Dialog.tenant_id == tenant_id)
    q = select(Dialog).where(Dialog.tenant_id == tenant_id)
    if date_from is not None:
        dt_from = datetime.combine(date_from, datetime.min.time())
        count_q = count_q.where(Dialog.updated_at >= dt_from)
        q = q.where(Dialog.updated_at >= dt_from)
    if date_to is not None:
        dt_to = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
        count_q = count_q.where(Dialog.updated_at < dt_to)
        q = q.where(Dialog.updated_at < dt_to)
    total = (await db.execute(count_q)).scalar() or 0
    q = q.order_by(Dialog.updated_at.desc()).limit(limit).offset(offset)
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
        cnt_result = await db.execute(select(func.count()).select_from(Message).where(Message.dialog_id == d.id))
        message_count = cnt_result.scalar() or 0
        lead_exists = await db.execute(select(exists().where(Lead.dialog_id == d.id, Lead.tenant_id == tenant_id)))
        has_lead = lead_exists.scalar() or False
        items.append({"dialog": d, "preview": preview, "message_count": message_count, "has_lead": has_lead})
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
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[int, list]:
    count_q = select(func.count()).select_from(Lead).where(Lead.tenant_id == tenant_id)
    q = select(Lead).where(Lead.tenant_id == tenant_id)
    if date_from is not None:
        dt_from = datetime.combine(date_from, datetime.min.time())
        count_q = count_q.where(Lead.updated_at >= dt_from)
        q = q.where(Lead.updated_at >= dt_from)
    if date_to is not None:
        dt_to = datetime.combine(date_to + timedelta(days=1), datetime.min.time())
        count_q = count_q.where(Lead.updated_at < dt_to)
        q = q.where(Lead.updated_at < dt_to)
    total = (await db.execute(count_q)).scalar() or 0
    q = q.order_by(Lead.updated_at.desc()).limit(limit).offset(offset)
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


# MCP servers
async def list_mcp_servers(db: AsyncSession, tenant_id: UUID) -> list[McpServer]:
    result = await db.execute(
        select(McpServer).where(McpServer.tenant_id == tenant_id).order_by(McpServer.created_at.desc())
    )
    return list(result.scalars().all())


async def get_mcp_server(db: AsyncSession, tenant_id: UUID, server_id: UUID) -> McpServer | None:
    result = await db.execute(
        select(McpServer).where(
            McpServer.id == server_id,
            McpServer.tenant_id == tenant_id,
        )
    )
    return result.scalar_one_or_none()


async def create_mcp_server(
    db: AsyncSession,
    tenant_id: UUID,
    name: str,
    base_url: str,
    enabled: bool = True,
) -> McpServer:
    s = McpServer(tenant_id=tenant_id, name=name.strip(), base_url=base_url.strip(), enabled=enabled)
    db.add(s)
    await db.flush()
    return s


async def update_mcp_server(
    db: AsyncSession,
    server: McpServer,
    name: str | None = None,
    base_url: str | None = None,
    enabled: bool | None = None,
) -> McpServer:
    if name is not None:
        server.name = name.strip()
    if base_url is not None:
        server.base_url = base_url.strip()
    if enabled is not None:
        server.enabled = enabled
    await db.flush()
    return server


async def delete_mcp_server(db: AsyncSession, server: McpServer) -> None:
    await db.delete(server)
    await db.flush()
