"""
Пользовательский чат с MCP: модель получает tools от Gallery, RAG и динамических серверов из БД,
вызывает их через tool_calls; цикл до финального ответа.
"""
import json
import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm_client import chat_once_with_tools
from app.services.mcp_client import (
    call_gallery_tool,
    call_mcp_tool_by_url,
    call_rag_tool,
    fetch_tools_from_url,
    get_gallery_tools_for_llm,
    get_rag_tools_for_llm,
    GALLERY_TOOL_NAMES,
    RAG_TOOL_NAMES,
)
from app.services.cabinet_service import list_mcp_servers, get_mcp_server

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


async def _get_all_tools_for_llm(tenant_id: UUID, db: AsyncSession) -> list[dict]:
    """Объединяет tools Gallery, RAG и включённых динамических MCP-серверов из БД. У динамических имён префикс mcp_<id>__."""
    out = []
    out.extend(await get_gallery_tools_for_llm())
    out.extend(await get_rag_tools_for_llm())
    servers = await list_mcp_servers(db, tenant_id)
    for s in servers:
        if not s.enabled:
            continue
        try:
            raw = await fetch_tools_from_url(s.base_url)
            for t in raw:
                name = t.get("name", "")
                if not name:
                    continue
                prefixed = f"mcp_{s.id}__{name}"
                desc = (t.get("description") or "").strip()
                schema = dict(t.get("inputSchema") or {})
                out.append({
                    "type": "function",
                    "function": {
                        "name": prefixed,
                        "description": desc or f"Инструмент {name} (сервер {s.name})",
                        "parameters": schema,
                    },
                })
        except Exception:
            continue
    return out


async def _call_tool(tenant_id: UUID, name: str, arguments: dict, db: AsyncSession) -> str:
    """Маршрутизирует вызов: Gallery, RAG или динамический MCP по префиксу mcp_<id>__."""
    if name in GALLERY_TOOL_NAMES:
        return await call_gallery_tool(tenant_id, name, arguments)
    if name in RAG_TOOL_NAMES:
        return await call_rag_tool(tenant_id, name, arguments)
    if name.startswith("mcp_") and "__" in name:
        prefix, inner_name = name.split("__", 1)
        server_id_str = prefix.replace("mcp_", "")
        try:
            server_uuid = UUID(server_id_str)
        except ValueError:
            return f"Ошибка: неверный идентификатор сервера в имени инструмента."
        server = await get_mcp_server(db, tenant_id, server_uuid)
        if not server:
            return f"Ошибка: MCP сервер не найден."
        try:
            return await call_mcp_tool_by_url(server.base_url, inner_name, arguments)
        except Exception as e:
            return f"Ошибка вызова инструмента: {e}"
    return f"Неизвестный инструмент: {name}."


async def run_user_chat_with_mcp_tools(
    tenant_id: UUID,
    system_prompt: str,
    messages: list[dict],
    db: AsyncSession,
) -> str:
    """
    Запускает диалог с моделью, передаёт tools от MCP (Gallery, RAG и динамические из БД).
    При tool_calls выполняет вызовы через MCP и повторяет запрос.
    Возвращает финальный текст ответа (без tool_calls).
    """
    tools = await _get_all_tools_for_llm(tenant_id, db)
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
                result = await _call_tool(tenant_id, name, arguments, db)
            except Exception as e:
                result = f"Ошибка: {e}"
            current_messages.append({
                "role": "tool",
                "tool_call_id": tid,
                "content": result,
            })

    return content or "Достигнут лимит вызовов инструментов."
