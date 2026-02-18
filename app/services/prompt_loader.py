"""Загрузка системного промпта: единый промпт тенанта или файл по умолчанию.
Промпт админ-чата — из БД или из файла."""
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Tenant


def load_prompt(base_dir: Path | None = None) -> str:
    """Промпт по умолчанию из файла (для восстановления и fallback)."""
    path = settings.get_prompt_path(base_dir)
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


async def load_prompt_for_tenant(db: AsyncSession, tenant_id: UUID) -> str:
    """
    Промпт пользовательского чат-бота для тенанта.
    Используется единый системный промпт из tenant.system_prompt; если пусто — из файла.
    """
    r = await db.execute(select(Tenant.system_prompt).where(Tenant.id == tenant_id))
    row = r.one_or_none()
    base = (row[0] or "").strip() if row else ""
    if base:
        return base
    return load_prompt()


def load_admin_prompt(base_dir: Path | None = None) -> str:
    """Промпт агента в личном кабинете."""
    path = settings.get_admin_prompt_path(base_dir)
    if not path.exists():
        raise FileNotFoundError(f"Admin prompt file not found: {path}")
    return path.read_text(encoding="utf-8")
