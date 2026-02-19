"""
Пользовательский чат с MCP: модель получает tools от Gallery и RAG,
вызывает их через tool_calls; цикл до финального ответа.
"""
import json
import re
from uuid import UUID

from app.config import settings
from app.llm_client import chat_once_with_tools
from app.services.mcp_client import call_mcp_tool, get_all_mcp_tools_for_llm

MAX_TOOL_ROUNDS = 10


def _inject_base_url_to_image_paths(text: str, tenant_id: UUID) -> str:
    """Подставляет frontend_base_url в пути вида /api/v1/tenants/.../me/gallery/..."""
    base = (settings.frontend_base_url or "").rstrip("/")
    if not base:
        return text
    # Пути от show_gallery: /api/v1/tenants/{tid}/me/gallery/groups/.../file
    pattern = r"(?<![\"'])(/api/v1/tenants/[^/]+/me/gallery/[^\s\"']+)"
    def repl(m: re.Match) -> str:
        return base + m.group(1)
    return re.sub(pattern, repl, text)


async def run_user_chat_with_mcp_tools(
    tenant_id: UUID,
    system_prompt: str,
    messages: list[dict],
) -> str:
    """
    Запускает диалог с моделью, передаёт tools от MCP (Gallery + RAG).
    При tool_calls выполняет вызовы через MCP и повторяет запрос.
    Возвращает финальный текст ответа (без tool_calls).
    """
    tools = await get_all_mcp_tools_for_llm()
    if not tools:
        # Fallback: один запрос без tools (модель не сможет вызвать галерею/RAG)
        from app.llm_client import chat_once
        return await chat_once(system_prompt, messages)

    current_messages = list(messages)
    for _ in range(MAX_TOOL_ROUNDS):
        out = await chat_once_with_tools(system_prompt, current_messages, tools)
        content = out.get("content") or ""
        tool_calls = out.get("tool_calls")

        if not tool_calls:
            return _inject_base_url_to_image_paths(content, tenant_id)

        # Формат assistant message с tool_calls для следующего запроса
        assistant_msg = {
            "role": "assistant",
            "content": content or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"]) if isinstance(tc.get("arguments"), dict) else (tc.get("arguments") or "{}"),
                    },
                }
                for tc in tool_calls
            ],
        }
        current_messages.append(assistant_msg)

        for tc in tool_calls:
            tid = tc["id"]
            name = tc.get("name") or ""
            arguments = tc.get("arguments") or {}
            try:
                result = await call_mcp_tool(tenant_id, name, arguments)
            except Exception as e:
                result = f"Ошибка: {e}"
            current_messages.append({
                "role": "tool",
                "tool_call_id": tid,
                "content": result,
            })

    return content or "Достигнут лимит вызовов инструментов."
