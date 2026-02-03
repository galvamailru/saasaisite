"""Load system prompt (per-tenant from DB or from file) and admin chat prompt."""
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings


def load_prompt(base_dir: Path | None = None) -> str:
    path = settings.get_prompt_path(base_dir)
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


async def load_prompt_for_tenant(db: AsyncSession, tenant_id: UUID) -> str:
    """Промпт чат-бота для тенанта: из БД (tenant.system_prompt), иначе из файла. Каждый админ SaaS настраивает своего бота."""
    from app.services.cabinet_service import get_tenant_by_id
    tenant = await get_tenant_by_id(db, tenant_id)
    if tenant and getattr(tenant, "system_prompt", None) and (tenant.system_prompt or "").strip():
        return (tenant.system_prompt or "").strip()
    return load_prompt()


def load_admin_prompt(base_dir: Path | None = None) -> str:
    """Промпт агента в личном кабинете: помогает админу наполнять чат клиента контентом."""
    path = settings.get_admin_prompt_path(base_dir)
    if not path.exists():
        raise FileNotFoundError(f"Admin prompt file not found: {path}")
    return path.read_text(encoding="utf-8")
