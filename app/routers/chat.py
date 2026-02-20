"""Chat: POST message -> SSE stream. Системный промпт из чанков. Галерея и RAG через MCP (tools)."""
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import ChatRequest
from app.services.chat_service import get_or_create_dialog, get_dialog_messages_for_llm, save_message
from app.services.leads import save_lead_if_contact
from app.services.prompt_loader import get_welcome_for_tenant, load_prompt_for_tenant, load_test_prompt_for_tenant
from app.services.cabinet_service import get_tenant_by_id
from app.services.user_chat_mcp_service import run_user_chat_with_mcp_tools
from app.services.test_chat_history import get_test_history, save_test_history

router = APIRouter(prefix="/api/v1/tenants", tags=["chat"])

# Размер чанка при «стриме» уже обработанного ответа (для плавного отображения)
_STREAM_CHUNK = 80


async def _sse_stream(
    tenant_id: UUID,
    user_id: str,
    dialog_id: UUID | None,
    message_text: str,
    db: AsyncSession,
    is_test: bool = False,
):
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        yield f"data: {json.dumps({'error': 'tenant not found'})}\n\n"
        return
    try:
        if is_test:
            prompt = await load_test_prompt_for_tenant(db, tenant_id)
        else:
            prompt = await load_prompt_for_tenant(db, tenant_id)
    except FileNotFoundError as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return
    if is_test:
        # Тестовый режим: история хранится только в памяти на сервере, без БД
        previous_history = get_test_history(tenant_id, user_id)
        history = previous_history + [{"role": "user", "content": message_text}]
        dialog = None
    else:
        dialog = await get_or_create_dialog(db, tenant_id, user_id, dialog_id)
        history = await get_dialog_messages_for_llm(db, dialog.id, tenant_id)
        history.append({"role": "user", "content": message_text})
        await save_message(db, tenant_id, user_id, dialog.id, "user", message_text)
        await save_lead_if_contact(db, tenant_id, user_id, dialog.id, message_text)
    try:
        final_text = await run_user_chat_with_mcp_tools(tenant_id, prompt, history, db)
    except Exception:
        if not is_test and dialog:
            await save_message(
                db,
                tenant_id,
                user_id,
                dialog.id,
                "assistant",
                "Ошибка при обращении к модели или инструментам.",
            )
        raise
    # В тестовом режиме после получения ответа обновляем историю в памяти (user + assistant)
    if is_test:
        prev = get_test_history(tenant_id, user_id)
        new_history = prev + [
            {"role": "user", "content": message_text},
            {"role": "assistant", "content": final_text},
        ]
        save_test_history(tenant_id, user_id, new_history)
    # Стримим клиенту уже обработанный ответ (чунками для плавного отображения)
    for i in range(0, len(final_text), _STREAM_CHUNK):
        yield f"data: {json.dumps({'content': final_text[i:i + _STREAM_CHUNK]})}\n\n"
    if not is_test and dialog:
        await save_message(db, tenant_id, user_id, dialog.id, "assistant", final_text)
    yield "data: [DONE]\n\n"


@router.post("/{tenant_id:uuid}/chat")
async def post_message(
    tenant_id: UUID,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    message_text = (request.message or "").strip()
    if not message_text:
        raise HTTPException(status_code=400, detail="message must not be empty")
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    # Лимит длины сообщения пользователя берём из настроек тенанта (по умолчанию 500 символов)
    from app.routers.cabinet import _get_limits_from_settings

    limits = _get_limits_from_settings(getattr(tenant, "settings", None) or {})
    max_len = limits["chat_max_user_message_chars"]
    if len(message_text) > max_len:
        raise HTTPException(
            status_code=400,
            detail=f"Сообщение слишком длинное. Максимум {max_len} символов.",
        )
    return StreamingResponse(
        _sse_stream(
            tenant_id,
            request.user_id,
            request.dialog_id,
            message_text,
            db,
            is_test=request.is_test,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{tenant_id:uuid}/chat/welcome")
async def get_welcome_message(
    tenant_id: UUID,
    db: AsyncSession = Depends(get_db),
    is_test: bool = False,
):
    """Возвращает приветственное сообщение из БД тенанта или из файла по умолчанию (без вызова модели)."""
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    try:
        text = await get_welcome_for_tenant(db, tenant_id, is_test=is_test)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"message": text}
