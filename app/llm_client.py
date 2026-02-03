"""HTTP client for DeepSeek LLM with streaming."""
import json
from collections.abc import AsyncIterator

import httpx

from app.config import settings


def _build_url() -> str:
    base = settings.deepseek_api_url.rstrip("/")
    return f"{base}/chat/completions"


async def stream_chat(
    system_prompt: str,
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    """
    Call DeepSeek chat completions with stream=True.
    Yields content deltas (text chunks) from the stream.
    """
    url = _build_url()
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            *messages,
        ],
        "stream": True,
    }
    full_content: list[str] = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choice = obj.get("choices") or []
                if not choice:
                    continue
                delta = choice[0].get("delta") or {}
                content = delta.get("content")
                if content is not None and isinstance(content, str):
                    full_content.append(content)
                    yield content


async def chat_once(system_prompt: str, messages: list[dict[str, str]]) -> str:
    """Один запрос к LLM без стриминга. Возвращает полный ответ."""
    full: list[str] = []
    async for chunk in stream_chat(system_prompt, messages):
        full.append(chunk)
    return "".join(full)
