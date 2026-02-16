"""CRUD для чанков промпта (макс. 500 символов). Сборка итогового промпта для LLM."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PromptChunk


async def list_chunks(db: AsyncSession, tenant_id: UUID) -> list[PromptChunk]:
    """Чанки тенанта по position."""
    r = await db.execute(
        select(PromptChunk)
        .where(PromptChunk.tenant_id == tenant_id)
        .order_by(PromptChunk.position, PromptChunk.id)
    )
    return list(r.scalars().all())


async def get_combined_prompt(db: AsyncSession, tenant_id: UUID) -> str:
    """Склеить чанки в один системный промпт для чат-бота."""
    chunks = await list_chunks(db, tenant_id)
    if not chunks:
        return ""
    return "\n\n".join(c.content.strip() for c in chunks if (c.content or "").strip())


async def create_chunk(db: AsyncSession, tenant_id: UUID, content: str, position: int | None = None) -> PromptChunk:
    """Добавить чанк. content обрезается до 500 символов."""
    content = (content or "").strip()[:500]
    if not content:
        raise ValueError("content must not be empty")
    if position is None:
        r = await db.execute(
            select(PromptChunk).where(PromptChunk.tenant_id == tenant_id).order_by(PromptChunk.position.desc())
        )
        last = r.scalar_one_or_none()
        position = (last.position + 1) if last is not None else 0
    chunk = PromptChunk(tenant_id=tenant_id, position=position, content=content)
    db.add(chunk)
    await db.flush()
    return chunk


async def update_chunk(
    db: AsyncSession, tenant_id: UUID, chunk_id: UUID, content: str | None = None, position: int | None = None
) -> PromptChunk | None:
    """Обновить чанк."""
    r = await db.execute(
        select(PromptChunk).where(PromptChunk.id == chunk_id, PromptChunk.tenant_id == tenant_id)
    )
    chunk = r.scalar_one_or_none()
    if not chunk:
        return None
    if content is not None:
        chunk.content = (content.strip())[:500]
    if position is not None:
        chunk.position = position
    await db.flush()
    return chunk


async def delete_chunk(db: AsyncSession, tenant_id: UUID, chunk_id: UUID) -> bool:
    """Удалить чанк."""
    r = await db.execute(
        select(PromptChunk).where(PromptChunk.id == chunk_id, PromptChunk.tenant_id == tenant_id)
    )
    chunk = r.scalar_one_or_none()
    if not chunk:
        return False
    await db.delete(chunk)
    await db.flush()
    return True
