"""Chat: POST message -> SSE stream. Системный промпт из чанков. Галерея и RAG через MCP (tools)."""
import json
import logging
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)

from app.database import get_db
from app.schemas import ChatMessageResponse, ChatRequest
from app.services.chat_service import get_or_create_dialog, get_dialog_messages_for_llm, save_message
from app.services.leads import save_lead_if_contact
from app.services.prompt_loader import get_welcome_for_tenant, load_prompt_for_tenant, load_test_prompt_for_tenant
from app.services.cabinet_service import get_tenant_by_id
from app.services.user_chat_mcp_service import run_user_chat_with_mcp_tools
from app.services.test_chat_history import get_test_history, save_test_history

router = APIRouter(prefix="/api/v1/tenants", tags=["chat"])

# Размер чанка при «стриме» уже обработанного ответа (для плавного отображения)
_STREAM_CHUNK = 80


async def _get_chat_reply(
    tenant_id: UUID,
    user_id: str,
    dialog_id: UUID | None,
    message_text: str,
    db: AsyncSession,
    is_test: bool = False,
) -> str:
    """Получить полный ответ бота (сохраняет сообщения в БД). Для SSE и для JSON-ответа."""
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    try:
        if is_test:
            prompt = await load_test_prompt_for_tenant(db, tenant_id)
        else:
            prompt = await load_prompt_for_tenant(db, tenant_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if is_test:
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
    if is_test:
        prev = get_test_history(tenant_id, user_id)
        new_history = prev + [
            {"role": "user", "content": message_text},
            {"role": "assistant", "content": final_text},
        ]
        save_test_history(tenant_id, user_id, new_history)
    if not is_test and dialog:
        await save_message(db, tenant_id, user_id, dialog.id, "assistant", final_text)
    return final_text


async def _sse_stream(
    tenant_id: UUID,
    user_id: str,
    dialog_id: UUID | None,
    message_text: str,
    db: AsyncSession,
    is_test: bool = False,
):
    try:
        final_text = await _get_chat_reply(
            tenant_id, user_id, dialog_id, message_text, db, is_test=is_test
        )
    except HTTPException as e:
        yield f"data: {json.dumps({'error': e.detail})}\n\n"
        return
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        return
    for i in range(0, len(final_text), _STREAM_CHUNK):
        yield f"data: {json.dumps({'content': final_text[i:i + _STREAM_CHUNK]})}\n\n"
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


@router.post("/{tenant_id:uuid}/chat/message", response_model=ChatMessageResponse)
async def post_message_json(
    tenant_id: UUID,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Ответ одним сообщением (JSON). Те же параметры, что и POST .../chat; в ответе — поле reply с полным текстом ответа бота.
    """
    message_text = (request.message or "").strip()
    if not message_text:
        raise HTTPException(status_code=400, detail="message must not be empty")
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    from app.routers.cabinet import _get_limits_from_settings

    limits = _get_limits_from_settings(getattr(tenant, "settings", None) or {})
    max_len = limits["chat_max_user_message_chars"]
    if len(message_text) > max_len:
        raise HTTPException(
            status_code=400,
            detail=f"Сообщение слишком длинное. Максимум {max_len} символов.",
        )
    reply = await _get_chat_reply(
        tenant_id,
        request.user_id,
        request.dialog_id,
        message_text,
        db,
        is_test=request.is_test,
    )
    return ChatMessageResponse(reply=reply)


@router.post("/{tenant_id:uuid}/telegram/webhook")
async def telegram_webhook(
    tenant_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Webhook для Telegram: Telegram шлёт сюда POST с телом Update.
    Мы получаем ответ боевого чата и доставляем его пользователю в Telegram одним исходящим запросом sendMessage — для этого нужен токен бота (tenant.settings.telegram_bot_token).
    """
    try:
        body = await request.json()
    except Exception:
        return {}
    message = body.get("message") if isinstance(body, dict) else None
    if not message or not isinstance(message, dict):
        return {}
    text = (message.get("text") or "").strip()
    from_obj = message.get("from") or {}
    chat_obj = message.get("chat") or {}
    from_id = from_obj.get("id")
    chat_id = chat_obj.get("id")
    if from_id is None or chat_id is None:
        return {}
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        return {}
    settings = getattr(tenant, "settings", None) or {}
    bot_token = (settings.get("telegram_bot_token") or "").strip()
    if not bot_token:
        _log.warning("telegram_webhook: tenant %s has no telegram_bot_token", tenant_id)
        return {}
    user_id = f"tg_{from_id}"
    reply_text = ""
    if not text:
        reply_text = "Отправьте текстовое сообщение."
    else:
        from app.routers.cabinet import _get_limits_from_settings
        limits = _get_limits_from_settings(settings)
        if len(text) > limits["chat_max_user_message_chars"]:
            reply_text = f"Сообщение слишком длинное. Максимум {limits['chat_max_user_message_chars']} символов."
        else:
            try:
                reply_text = await _get_chat_reply(tenant_id, user_id, None, text, db, is_test=False)
            except Exception as e:
                _log.exception("telegram_webhook chat reply failed: %s", e)
                reply_text = "Ошибка при обработке сообщения. Попробуйте позже."
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": reply_text[:4096]},
            )
            if r.status_code != 200:
                _log.warning("telegram sendMessage failed: %s %s", r.status_code, r.text)
    except Exception as e:
        _log.exception("telegram sendMessage request failed: %s", e)
    return {}


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
