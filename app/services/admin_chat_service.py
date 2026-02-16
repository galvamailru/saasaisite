"""Админ-чат: диалог без команд. Бот понимает намерения и выполняет действия с чанками промпта через [EXECUTE]."""
import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm_client import chat_once
from app.services.prompt_chunk_service import list_chunks, create_chunk, update_chunk, delete_chunk
from app.services.prompt_loader import load_admin_prompt, load_prompt
from app.services.cabinet_service import get_tenant_by_id

EXECUTE_BLOCK_RE = re.compile(r"\[EXECUTE\](.*?)\[/EXECUTE\]", re.DOTALL | re.IGNORECASE)

ADMIN_SYSTEM_PROMPT_FALLBACK = """Ты — Админ-помощник. Только помощь в заполнении промпта чат-бота чанками (до 2000 символов каждый). Веди диалог пошагово, задавай уточняющие вопросы (роль бота, стиль, ограничения), предлагай формулировки чанков. При согласии добавляй в конец ответа блок [EXECUTE]...[/EXECUTE]. Команды: ADD_CHUNK, EDIT_CHUNK <id> <текст>, DELETE_CHUNK <id>. Администратор команд не вводит."""


def _get_admin_prompt() -> str:
    try:
        return load_admin_prompt()
    except FileNotFoundError:
        return ADMIN_SYSTEM_PROMPT_FALLBACK


async def _build_state(db: AsyncSession, tenant_id: UUID, user_id: str) -> str:
    """Текущее состояние: чанки промпта — для контекста LLM."""
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        return ""
    chunks = await list_chunks(db, tenant_id)
    lines = ["Текущее состояние (промпт бота для клиентов — чанки до 2000 символов):"]
    if not chunks:
        lines.append("  (пока нет чанков; добавьте в разделе «Промпт» или через этот чат.)")
    else:
        for c in chunks:
            q = (c.question or "").strip()
            q_part = f' вопрос: "{q[:80]}{"…" if len(q) > 80 else ""}" |' if q else " "
            prev = (c.content or "")[:150] + ("..." if len(c.content or "") > 150 else "")
            lines.append(f"  [id={c.id}] position={c.position} |{q_part} ответ: {prev}")
    return "\n".join(lines)


async def _parse_and_execute(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    block_content: str,
) -> list[str]:
    """Парсит блок [EXECUTE] и выполняет команду над чанками. Возвращает список сообщений."""
    lines = block_content.strip().split("\n")
    if not lines:
        return []
    cmd = lines[0].strip().upper()
    payload = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    results = []
    try:
        if cmd == "ADD_CHUNK":
            lines = [s for s in payload.split("\n") if s is not None]
            question: str | None = (lines[0].strip()[:1000] if lines and lines[0].strip() else None)
            if len(lines) > 1:
                content = "\n".join(lines[1:]).strip()[:2000]
            else:
                content = (lines[0].strip() if lines else "")[:2000]
            if not content:
                results.append("Ошибка: укажите текст чанка (ответ пользователя). После первой строки можно указать вопрос админа.")
            else:
                chunk = await create_chunk(db, tenant_id, content, position=None, question=question)
                results.append(f"Чанк добавлен (id: {chunk.id}).")
        elif cmd == "EDIT_CHUNK":
            parts = payload.split(None, 1)
            chunk_id_s = (parts[0] or "").strip()
            new_text = (parts[1] or "").strip()[:2000] if len(parts) > 1 else ""
            if not chunk_id_s:
                results.append("Ошибка: укажите id чанка в EDIT_CHUNK.")
            else:
                try:
                    cid = UUID(chunk_id_s)
                    chunk = await update_chunk(db, tenant_id, cid, content=new_text if new_text else None)
                    if chunk:
                        results.append(f"Чанк {cid} обновлён.")
                    else:
                        results.append("Чанк не найден.")
                except ValueError:
                    results.append("Неверный id чанка.")
        elif cmd == "DELETE_CHUNK":
            chunk_id_s = payload.strip()
            if not chunk_id_s:
                results.append("Ошибка: укажите id чанка в DELETE_CHUNK.")
            else:
                try:
                    cid = UUID(chunk_id_s)
                    ok = await delete_chunk(db, tenant_id, cid)
                    if ok:
                        results.append(f"Чанк {cid} удалён.")
                    else:
                        results.append("Чанк не найден.")
                except ValueError:
                    results.append("Неверный id чанка.")
        else:
            results.append(f"Неизвестная команда: {cmd}. Доступны: ADD_CHUNK, EDIT_CHUNK, DELETE_CHUNK.")
    except Exception as e:
        results.append(f"Ошибка: {e}")
    return results


def _strip_execute_blocks(reply: str) -> str:
    return EXECUTE_BLOCK_RE.sub("", reply).strip()


async def handle_admin_message(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    message: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """
    Диалог без команд. Бот получает текущие чанки промпта, историю и сообщение.
    В ответе может быть блок [EXECUTE]...[/EXECUTE] — выполняем команды и убираем блок.
    """
    text = (message or "").strip()
    if not text:
        return "Напишите, чем могу помочь: добавить или изменить чанки промпта бота для клиентов?"

    state = await _build_state(db, tenant_id, user_id)
    system_prompt = _get_admin_prompt()
    system_with_state = system_prompt.rstrip() + "\n\n---\n" + state

    messages = []
    for h in (history or [])[-20:]:
        role = h.get("role", "user")
        content = (h.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": text})

    reply = await chat_once(system_with_state, messages)
    reply = (reply or "").strip()

    executed = []
    for m in EXECUTE_BLOCK_RE.finditer(reply):
        block = m.group(1).strip()
        executed.extend(await _parse_and_execute(db, tenant_id, user_id, block))

    reply_clean = _strip_execute_blocks(reply)
    if executed:
        reply_clean = reply_clean.rstrip()
        if reply_clean:
            reply_clean += "\n\n"
        reply_clean += "✓ " + "; ".join(executed)
    return reply_clean or "Готово."
