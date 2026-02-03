"""Load system prompt and admin chat prompt from file (path from config)."""
from pathlib import Path

from app.config import settings


def load_prompt(base_dir: Path | None = None) -> str:
    path = settings.get_prompt_path(base_dir)
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def load_admin_prompt(base_dir: Path | None = None) -> str:
    """Промпт агента в личном кабинете: помогает админу наполнять чат клиента контентом."""
    path = settings.get_admin_prompt_path(base_dir)
    if not path.exists():
        raise FileNotFoundError(f"Admin prompt file not found: {path}")
    return path.read_text(encoding="utf-8")
