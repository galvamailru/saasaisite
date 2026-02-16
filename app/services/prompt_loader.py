"""Загрузка системного промпта: из чанков тенанта или из файла по умолчанию. Промпт админ-чата — из файла."""
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.prompt_chunk_service import get_combined_prompt


def load_prompt(base_dir: Path | None = None) -> str:
    """Промпт по умолчанию из файла (fallback при отсутствии чанков)."""
    path = settings.get_prompt_path(base_dir)
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


async def load_prompt_for_tenant(db: AsyncSession, tenant_id: UUID) -> str:
    """Промпт чат-бота для тенанта: из чанков (БД), иначе из файла."""
    combined = await get_combined_prompt(db, tenant_id)
    if combined.strip():
        return combined.strip()
    return load_prompt()


def load_admin_prompt(base_dir: Path | None = None) -> str:
    """Промпт агента в личном кабинете."""
    path = settings.get_admin_prompt_path(base_dir)
    if not path.exists():
        raise FileNotFoundError(f"Admin prompt file not found: {path}")
    return path.read_text(encoding="utf-8")
