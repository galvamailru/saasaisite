"""
Клиент MCP для микросервисов Gallery и RAG.
Получает список tools (tools/list), выполняет вызовы (tools/call).
tenant_id подставляется при вызове в аргументы, не передаётся в модель.
"""
import json
from uuid import UUID

import httpx

from app.config import settings

_GALLERY_MCP = f"{settings.gallery_service_url.rstrip('/')}/mcp"
_RAG_MCP = f"{settings.rag_service_url.rstrip('/')}/mcp"


async def _mcp_request(url: str, method: str, params: dict | None = None) -> dict:
    """Отправляет JSON-RPC 2.0 запрос, возвращает result или поднимает ошибку."""
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", "MCP error"))
    return data.get("result", {})


def _mcp_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/mcp"


async def fetch_tools_from_url(base_url: str) -> list[dict]:
    """
    Запрашивает tools/list у MCP-сервера по base_url (например http://host:8010).
    Возвращает список сырых tools: [{"name", "description", "inputSchema"}, ...].
    При ошибке соединения возвращает [] или поднимает исключение — вызывающий код решает.
    """
    url = _mcp_url(base_url)
    try:
        result = await _mcp_request(url, "tools/list")
        return result.get("tools") or []
    except Exception:
        raise


def _mcp_tool_to_deepseek(mcp_tool: dict, drop_tenant_id: bool = True) -> dict:
    """Конвертирует MCP tool в формат DeepSeek/OpenAI (function)."""
    name = mcp_tool.get("name", "")
    description = mcp_tool.get("description", "")
    schema = dict(mcp_tool.get("inputSchema") or {})
    if drop_tenant_id and "properties" in schema and "tenant_id" in schema.get("properties", {}):
        props = {k: v for k, v in schema["properties"].items() if k != "tenant_id"}
        req = [x for x in schema.get("required", []) if x != "tenant_id"]
        schema = {"type": "object", "properties": props}
        if req:
            schema["required"] = req
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }


async def get_gallery_tools_for_llm() -> list[dict]:
    """Список tools галереи в формате для DeepSeek (без tenant_id в параметрах)."""
    try:
        result = await _mcp_request(_GALLERY_MCP, "tools/list")
        tools = result.get("tools") or []
        return [_mcp_tool_to_deepseek(t) for t in tools]
    except Exception:
        return []


async def get_rag_tools_for_llm() -> list[dict]:
    """Список tools RAG в формате для DeepSeek (tenant_id убираем для list/search)."""
    try:
        result = await _mcp_request(_RAG_MCP, "tools/list")
        tools = result.get("tools") or []
        return [_mcp_tool_to_deepseek(t) for t in tools]
    except Exception:
        return []


async def get_all_mcp_tools_for_llm() -> list[dict]:
    """Объединённый список tools Gallery + RAG для передачи в модель."""
    gallery = await get_gallery_tools_for_llm()
    rag = await get_rag_tools_for_llm()
    return gallery + rag


async def call_gallery_tool(tenant_id: UUID, name: str, arguments: dict) -> str:
    """Вызов tool галереи. tenant_id подставляется в arguments."""
    args = dict(arguments)
    args["tenant_id"] = str(tenant_id)
    result = await _mcp_request(_GALLERY_MCP, "tools/call", {"name": name, "arguments": args})
    content = result.get("content") or []
    for part in content:
        if part.get("type") == "text":
            return part.get("text", "")
    return ""


async def call_rag_tool(tenant_id: UUID, name: str, arguments: dict) -> str:
    """Вызов tool RAG. tenant_id подставляется для list_documents и search_documents."""
    args = dict(arguments)
    if name in ("list_documents", "search_documents"):
        args["tenant_id"] = str(tenant_id)
    result = await _mcp_request(_RAG_MCP, "tools/call", {"name": name, "arguments": args})
    content = result.get("content") or []
    for part in content:
        if part.get("type") == "text":
            return part.get("text", "")
    return ""


# Имена tools по сервисам для маршрутизации
GALLERY_TOOL_NAMES = {"list_galleries", "show_gallery"}
RAG_TOOL_NAMES = {"list_documents", "get_document", "search_documents"}


async def call_mcp_tool_by_url(base_url: str, name: str, arguments: dict) -> str:
    """Вызывает tool по имени на произвольном MCP-сервере по base_url."""
    url = _mcp_url(base_url)
    result = await _mcp_request(url, "tools/call", {"name": name, "arguments": arguments})
    content = result.get("content") or []
    for part in content:
        if part.get("type") == "text":
            return part.get("text", "")
    return ""


async def call_mcp_tool(tenant_id: UUID, name: str, arguments: dict) -> str:
    """Вызывает tool по имени через соответствующий MCP-сервер (Gallery, RAG или динамический по префиксу mcp_<id>__)."""
    if name in GALLERY_TOOL_NAMES:
        return await call_gallery_tool(tenant_id, name, arguments)
    if name in RAG_TOOL_NAMES:
        return await call_rag_tool(tenant_id, name, arguments)
    if name.startswith("mcp_") and "__" in name:
        # Динамический сервер: mcp_<uuid>__toolname — маршрутизация в user_chat_mcp_service через call_mcp_tool_with_db
        return f"Неизвестный инструмент: {name} (вызов динамического сервера выполняется в сервисе чата)."
    return f"Неизвестный инструмент: {name}."
