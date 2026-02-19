"""
Клиент MCP: запрос tools/list и tools/call по произвольному base_url.
Подключения MCP задаются только из БД (страница «MCP серверы» в кабинете).
"""
import httpx


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


async def call_mcp_tool_by_url(base_url: str, name: str, arguments: dict) -> str:
    """Вызывает tool по имени на произвольном MCP-сервере по base_url."""
    url = _mcp_url(base_url)
    result = await _mcp_request(url, "tools/call", {"name": name, "arguments": arguments})
    content = result.get("content") or []
    for part in content:
        if part.get("type") == "text":
            return part.get("text", "")
    return ""
