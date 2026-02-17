"""Прокси-вызовы к микросервисам Gallery и RAG из кабинета (JWT + tenant_id)."""
from uuid import UUID

import httpx

from app.config import settings


async def gallery_request(
    method: str,
    path: str,
    tenant_id: UUID,
    json_body: dict | None = None,
) -> tuple[int, str]:
    """Вызов API галереи. path без ведущего слэша. Возвращает (status_code, text)."""
    base = settings.gallery_service_url.rstrip("/")
    url = f"{base}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        if method == "GET":
            r = await client.get(url)
        elif method == "POST":
            r = await client.post(url, json=json_body or {})
        elif method == "PATCH":
            r = await client.patch(url, json=json_body or {})
        elif method == "DELETE":
            r = await client.delete(url)
        else:
            r = await client.request(method, url, json=json_body)
        return r.status_code, r.text


async def rag_request(
    method: str,
    path: str,
    params: dict | None = None,
    files: dict | None = None,
    data: dict | None = None,
) -> tuple[int, str]:
    """Вызов API RAG. Возвращает (status_code, text)."""
    base = settings.rag_service_url.rstrip("/")
    url = f"{base}{path}"
    async with httpx.AsyncClient(timeout=120.0) as client:
        if method == "GET":
            r = await client.get(url, params=params)
        elif method == "POST":
            if files:
                r = await client.post(url, params=params, files=files, data=data)
            else:
                r = await client.post(url, params=params, json=data or {})
        elif method == "DELETE":
            r = await client.delete(url)
        else:
            r = await client.request(method, url, params=params, json=data)
        return r.status_code, r.text
