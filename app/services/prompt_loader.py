"""Загрузка системного промпта: базовый системный промпт тенанта + чанки, либо файл по умолчанию.
Промпт админ-чата — из файла."""
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Tenant
from app.services.prompt_chunk_service import get_combined_prompt


def load_prompt(base_dir: Path | None = None) -> str:
    """Промпт по умолчанию из файла (fallback при отсутствии системного промпта и чанков)."""
    path = settings.get_prompt_path(base_dir)
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


async def load_prompt_for_tenant(db: AsyncSession, tenant_id: UUID) -> str:
    """
    Промпт пользовательского чат-бота для тенанта.

    1. Берём базовый системный промпт из tenant.system_prompt (если есть).
    2. Добавляем текст из чанков prompt_chunk (через get_combined_prompt).
    3. Если и системный промпт, и чанки пустые — берём промпт из файла.
    """
    # Базовый системный промпт
    r = await db.execute(select(Tenant.system_prompt).where(Tenant.id == tenant_id))
    row = r.one_or_none()
    base = (row[0] or "").strip() if row else ""

    # Чанки промпта
    combined_chunks = (await get_combined_prompt(db, tenant_id)).strip()

    parts: list[str] = []
    if base:
        parts.append(base)
    if combined_chunks:
        parts.append(combined_chunks)

    if parts:
        return "\n\n".join(parts)
    return load_prompt()


def load_admin_prompt(base_dir: Path | None = None) -> str:
    """Промпт агента в личном кабинете."""
    path = settings.get_admin_prompt_path(base_dir)
    if not path.exists():
        raise FileNotFoundError(f"Admin prompt file not found: {path}")
    return path.read_text(encoding="utf-8")
