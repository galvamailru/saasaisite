"""Админ-чат: диалог-помощник. Единый системный промпт админ-бота из БД или файла."""
import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm_client import chat_once
from app.services.prompt_loader import load_admin_prompt
from app.services.admin_prompt_service import get_admin_system_prompt

EXECUTE_BLOCK_RE = re.compile(r"\[EXECUTE\](.*?)\[/EXECUTE\]", re.DOTALL | re.IGNORECASE)

ADMIN_SYSTEM_PROMPT_FALLBACK = """Ты — Админ-помощник. Помогаешь настроить промпт чат-бота для клиентов. Промпт редактируется в разделе «Профиль» (системный промпт бота) и «Промпт админ-бота». Веди диалог пошагово, задавай уточняющие вопросы. Администратор команд не вводит."""


async def _get_admin_prompt_assembled(db: AsyncSession, tenant_id: UUID) -> str:
    """Системный промпт админ-бота: из БД или из файла по умолчанию."""
    system = await get_admin_system_prompt(db, tenant_id)
    if system and system.strip():
        return system.strip()
    try:
        return load_admin_prompt()
    except FileNotFoundError:
        return ADMIN_SYSTEM_PROMPT_FALLBACK


def _build_state() -> str:
    """Краткий контекст для LLM: где редактируются промпты."""
    return (
        "Промпт клиентского бота (единый текст) редактируется в разделе «Профиль». "
        "Промпт админ-бота — в разделе «Промпт админ-бота». Оба можно восстановить из файла по умолчанию."
    )


def _strip_execute_blocks(reply: str) -> str:
    return EXECUTE_BLOCK_RE.sub("", reply).strip()


async def handle_admin_message(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    message: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """
    Диалог админ-помощника. Бот использует единый системный промпт из БД или файла.
    Блоки [EXECUTE] в ответе удаляются (команды по чанкам отключены).
    """
    text = (message or "").strip()
    if not text:
        return "Напишите, чем могу помочь: настроить промпт бота для клиентов?"

    state = _build_state()
    system_prompt = await _get_admin_prompt_assembled(db, tenant_id)
    system_with_state = system_prompt.rstrip() + "\n\n---\n" + state

    messages = []
    for h in (history or [])[-20:]:
        role = h.get("role", "user")
        content = (h.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text})

    reply = await chat_once(system_with_state, messages)
    reply = (reply or "").strip()
    return _strip_execute_blocks(reply) or "Готово."
