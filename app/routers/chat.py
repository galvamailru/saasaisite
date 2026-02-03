"""Chat: POST message -> SSE stream. Триггеры добавляются в промпт и при срабатывании файл выводится в ответ."""
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.llm_client import stream_chat
from app.schemas import ChatRequest
from app.services.chat_service import get_or_create_dialog, get_dialog_messages_for_llm, save_message
from app.services.prompt_loader import load_prompt_for_tenant
from app.services.cabinet_service import get_tenant_by_id
from app.services.file_service import get_triggered_files_for_tenant, get_presigned_url

router = APIRouter(prefix="/api/v1/tenants", tags=["chat"])


def _build_prompt_with_triggers(base_prompt: str, triggered_files: list) -> str:
    """Добавляет к системному промпту блок про триггеры: при упоминании фразы — добавить ссылку на файл."""
    if not triggered_files:
        return base_prompt
    lines = []
    for uf in triggered_files:
        url = get_presigned_url(uf.minio_key, expires=86400)
        lines.append(f"- Фраза «{uf.trigger}» → файл «{uf.filename}»: {url}")
    block = "\n\nТриггеры (если пользователь упоминает фразу, добавь в ответ ссылку на файл):\n" + "\n".join(lines)
    return base_prompt.rstrip() + block


def _matched_trigger_files(message_text: str, triggered_files: list) -> list:
    """Файлы, чей триггер сработал (подстрока в сообщении пользователя, без учёта регистра)."""
    text = (message_text or "").strip().lower()
    if not text:
        return []
    return [uf for uf in triggered_files if uf.trigger and uf.trigger.strip().lower() in text]


async def _sse_stream(tenant_id: UUID, user_id: str, dialog_id: UUID | None, message_text: str, db: AsyncSession):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        yield f"data: {json.dumps({'error': 'tenant not found'})}\n\n"
        return
    try:
        base_prompt = await load_prompt_for_tenant(db, tenant_id)
    except FileNotFoundError as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return
    triggered_files = await get_triggered_files_for_tenant(db, tenant_id)
    prompt = _build_prompt_with_triggers(base_prompt, triggered_files)
    dialog = await get_or_create_dialog(db, tenant_id, user_id, dialog_id)
    history = await get_dialog_messages_for_llm(db, dialog.id)
    history.append({"role": "user", "content": message_text})
    await save_message(db, tenant_id, user_id, dialog.id, "user", message_text)
    full_response: list[str] = []
    try:
        async for chunk in stream_chat(prompt, history):
            full_response.append(chunk)
            yield f"data: {json.dumps({'content': chunk})}\n\n"
    except Exception:
        full_text = "".join(full_response)
        if full_text:
            await save_message(db, tenant_id, user_id, dialog.id, "assistant", full_text)
        raise
    full_text = "".join(full_response)
    matched = _matched_trigger_files(message_text, triggered_files)
    for uf in matched:
        url = get_presigned_url(uf.minio_key, expires=86400)
        full_text += f"\n\n[Файл: {uf.filename}]({url})"
    await save_message(db, tenant_id, user_id, dialog.id, "assistant", full_text)
    if matched:
        for uf in matched:
            url = get_presigned_url(uf.minio_key, expires=86400)
            chunk = f"\n\n[Файл: {uf.filename}]({url})"
            yield f"data: {json.dumps({'content': chunk})}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/{tenant_id:uuid}/chat")
async def post_message(
    tenant_id: UUID,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")
    return StreamingResponse(
        _sse_stream(tenant_id, request.user_id, request.dialog_id, request.message.strip(), db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
