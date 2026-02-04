"""Админ-чат: диалог без команд. Бот понимает намерения, ведёт диалог и выполняет действия через блок [EXECUTE] в ответе."""
import re
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm_client import chat_once
from app.models import GalleryItem
from app.services.file_service import list_user_files, set_file_trigger
from app.services.gallery_service import (
    list_galleries,
    create_gallery,
    delete_gallery,
    add_file_to_gallery,
    remove_from_gallery,
)
from app.services.prompt_loader import load_admin_prompt, load_prompt
from app.services.cabinet_service import get_tenant_by_id

EXECUTE_BLOCK_RE = re.compile(r"\[EXECUTE\](.*?)\[/EXECUTE\]", re.DOTALL | re.IGNORECASE)

ADMIN_SYSTEM_PROMPT_FALLBACK = """Ты — контент-менеджер в кабинете владельца чат-сайта. Веди диалог: спрашивай, чем помочь (промпт, галерея, триггеры), задавай уточняющие вопросы, предлагай изменения. Когда администратор согласен — выполняй действие, добавив в конец ответа блок [EXECUTE]...[/EXECUTE]. Администратор команд не вводит."""


def _get_admin_prompt() -> str:
    try:
        return load_admin_prompt()
    except FileNotFoundError:
        return ADMIN_SYSTEM_PROMPT_FALLBACK


async def _build_state(db: AsyncSession, tenant_id: UUID, user_id: str) -> str:
    """Текущее состояние: промпт бота, файлы, галереи — для контекста LLM."""
    tenant = await get_tenant_by_id(db, tenant_id)
    if not tenant:
        return ""
    lines = ["Текущее состояние (используй при ответах):"]
    current_prompt = getattr(tenant, "system_prompt", None) and (tenant.system_prompt or "").strip()
    if not current_prompt:
        try:
            current_prompt = load_prompt()
        except FileNotFoundError:
            current_prompt = "(общий по умолчанию)"
    lines.append("[Промпт бота для клиентов]")
    lines.append(current_prompt[:4000] + ("..." if len(current_prompt or "") > 4000 else ""))
    lines.append("")
    _, files = await list_user_files(db, tenant_id, user_id, limit=100, offset=0)
    lines.append("[Файлы: id | имя | триггер]")
    for uf in files:
        trigger = f" | «{uf.trigger}»" if uf.trigger else ""
        lines.append(f"  {uf.id} | {uf.filename}{trigger}")
    if not files:
        lines.append("  (пока нет; загружаются в разделе «Файлы»)")
    lines.append("")
    galleries = await list_galleries(db, tenant_id, user_id)
    lines.append("[Галереи: id | название | кол-во фото]")
    for g in galleries:
        cnt = await db.execute(
            select(func.count()).select_from(GalleryItem).where(GalleryItem.gallery_id == g.id)
        )
        n = cnt.scalar() or 0
        lines.append(f"  {g.id} | {g.name} | {n}")
    if not galleries:
        lines.append("  (пока нет)")
    return "\n".join(lines)


async def _parse_and_execute(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    block_content: str,
) -> list[str]:
    """Парсит содержимое одного блока [EXECUTE] и выполняет команду. Возвращает список сообщений об результате."""
    lines = block_content.strip().split("\n")
    if not lines:
        return []
    cmd = lines[0].strip().upper()
    payload = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    results = []
    try:
        if cmd == "SET_PROMPT":
            tenant = await get_tenant_by_id(db, tenant_id)
            if tenant:
                tenant.system_prompt = payload[:65535] if len(payload) > 65535 else payload
                await db.flush()
                results.append("Промпт бота заменён.")
        elif cmd == "APPEND_PROMPT":
            tenant = await get_tenant_by_id(db, tenant_id)
            if tenant:
                current = (tenant.system_prompt or "").strip()
                new = (current + "\n\n" + payload).strip()[:65535]
                tenant.system_prompt = new
                await db.flush()
                results.append("В промпт добавлен абзац.")
        elif cmd == "ADD_TRIGGER":
            parts = payload.split("\n", 1)
            file_id_s = (parts[0] or "").strip()
            phrase = (parts[1] or "").strip() if len(parts) > 1 else ""
            if not file_id_s:
                results.append("Ошибка: укажи file_id в ADD_TRIGGER.")
            else:
                try:
                    fid = UUID(file_id_s)
                    uf = await set_file_trigger(db, tenant_id, user_id, fid, phrase[:128] if phrase else None)
                    if uf:
                        results.append(f"Триггер привязан к файлу «{uf.filename}».")
                    else:
                        results.append("Файл не найден.")
                except ValueError:
                    results.append("Неверный file_id.")
        elif cmd == "CLEAR_TRIGGER":
            try:
                fid = UUID(payload.strip())
                uf = await set_file_trigger(db, tenant_id, user_id, fid, None)
                if uf:
                    results.append(f"Триггер у файла «{uf.filename}» убран.")
                else:
                    results.append("Файл не найден.")
            except ValueError:
                results.append("Неверный file_id.")
        elif cmd == "CREATE_GALLERY":
            name = payload.strip()[:256] or "Галерея"
            g = await create_gallery(db, tenant_id, user_id, name)
            results.append(f"Галерея «{g.name}» создана (id: {g.id}).")
        elif cmd == "ADD_TO_GALLERY":
            parts = payload.strip().split()
            if len(parts) >= 2:
                try:
                    gid, fid = UUID(parts[0]), UUID(parts[1])
                    item = await add_file_to_gallery(db, tenant_id, user_id, gid, fid)
                    if item:
                        results.append("Файл добавлен в галерею.")
                    else:
                        results.append("Галерея или файл не найдены.")
                except ValueError:
                    results.append("Неверные id.")
            else:
                results.append("Формат: ADD_TO_GALLERY\\n<gallery_id>\\n<file_id>")
        else:
            results.append(f"Неизвестная команда: {cmd}")
    except Exception as e:
        results.append(f"Ошибка: {e}")
    return results


def _strip_execute_blocks(reply: str) -> str:
    """Удаляет из ответа все блоки [EXECUTE]...[/EXECUTE] (их администратор не видит)."""
    return EXECUTE_BLOCK_RE.sub("", reply).strip()


async def handle_admin_message(
    db: AsyncSession,
    tenant_id: UUID,
    user_id: str,
    message: str,
    history: list[dict[str, str]] | None = None,
) -> str:
    """
    Диалог без команд. Бот получает текущее состояние (промпт, файлы, галереи), историю и новое сообщение.
    В ответе бот может добавить блок [EXECUTE]...[/EXECUTE] — мы выполняем команды и убираем блок из ответа.
    """
    text = (message or "").strip()
    if not text:
        return "Напишите, чем могу помочь: изменить промпт бота, добавить картинки в галерею, настроить триггеры?"

    state = await _build_state(db, tenant_id, user_id)
    system_prompt = _get_admin_prompt()
    system_with_state = system_prompt.rstrip() + "\n\n---\n" + state

    messages = []
    for h in (history or [])[-20:]:  # последние 20 пар
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
