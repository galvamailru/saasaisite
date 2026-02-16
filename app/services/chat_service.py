"""Chat: get/create dialog, save message, get history for LLM."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Dialog, Message


async def get_or_create_dialog(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    dialog_id: UUID | None,
) -> Dialog:
    if dialog_id:
        result = await db.execute(
            select(Dialog).where(
                Dialog.id == dialog_id,
                Dialog.tenant_id == tenant_id,
                Dialog.user_id == user_id,
            )
        )
        dialog = result.scalar_one_or_none()
        if dialog:
            return dialog
    dialog = Dialog(tenant_id=tenant_id, user_id=user_id)
    db.add(dialog)
    await db.flush()
    return dialog


async def save_message(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    dialog_id: UUID,
    role: str,
    content: str,
) -> None:
    msg = Message(
        tenant_id=tenant_id,
        user_id=user_id,
        dialog_id=dialog_id,
        role=role,
        content=content,
    )
    db.add(msg)
    await db.flush()


async def get_dialog_messages_for_llm(
    db: AsyncSession, dialog_id: UUID, tenant_id: UUID
) -> list[dict[str, str]]:
    """История диалога для LLM. Фильтр по tenant_id — изоляция данных тенанта."""
    result = await db.execute(
        select(Message.role, Message.content)
        .where(Message.dialog_id == dialog_id, Message.tenant_id == tenant_id)
        .order_by(Message.created_at)
    )
    rows = result.all()
    return [{"role": r.role, "content": r.content} for r in rows]
