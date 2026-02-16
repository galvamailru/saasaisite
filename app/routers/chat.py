"""Chat: POST message -> SSE stream. Системный промпт из чанков тенанта."""
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.llm_client import stream_chat
from app.schemas import ChatRequest
from app.services.chat_service import get_or_create_dialog, get_dialog_messages_for_llm, save_message
from app.services.leads import save_lead_if_contact
from app.services.prompt_loader import load_prompt_for_tenant
from app.services.cabinet_service import get_tenant_by_id

router = APIRouter(prefix="/api/v1/tenants", tags=["chat"])


async def _sse_stream(tenant_id: UUID, user_id: str, dialog_id: UUID | None, message_text: str, db: AsyncSession):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        yield f"data: {json.dumps({'error': 'tenant not found'})}\n\n"
        return
    try:
        prompt = await load_prompt_for_tenant(db, tenant_id)
    except FileNotFoundError as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return
    dialog = await get_or_create_dialog(db, tenant_id, user_id, dialog_id)
    history = await get_dialog_messages_for_llm(db, dialog.id)
    history.append({"role": "user", "content": message_text})
    await save_message(db, tenant_id, user_id, dialog.id, "user", message_text)
    await save_lead_if_contact(db, tenant_id, user_id, dialog.id, message_text)
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
    await save_message(db, tenant_id, user_id, dialog.id, "assistant", full_text)
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
